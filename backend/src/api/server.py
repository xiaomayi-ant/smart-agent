import asyncio
import json
import uuid
import os
from typing import Dict, Any, List
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from ..core.config import settings
from ..core.graph import graph, GraphState, create_graph, register_stream_callback
from ..models.types import ThreadCreateResponse, StreamRequest
from ..tools.registry import TOOL_BY_NAME
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from ..store.threads_pg import (
    ensure_thread,
    insert_message as pg_insert_message,
    load_messages as pg_load_messages,
    delete_thread as pg_delete_thread,
    touch_thread as pg_touch_thread,
    get_thread_owner,
)

# Import document routes (optional)
try:
    from .document_routes import router as document_router
    DOCUMENT_ROUTES_AVAILABLE = True
except ImportError as e:
    print(f"[Server] Document routes not available: {e}")
    DOCUMENT_ROUTES_AVAILABLE = False
# Import websearch routes (optional)
try:
    from .websearch_routes import router as websearch_router
    WEBSEARCH_ROUTES_AVAILABLE = True
except ImportError as e:
    print(f"[Server] Websearch routes not available: {e}")
    WEBSEARCH_ROUTES_AVAILABLE = False

# Import ASR routes (optional, behind feature flag)
ASR_ROUTES_AVAILABLE = False
if getattr(settings, "enable_voice", False):
    try:
        from .asr_routes import router as asr_router
        ASR_ROUTES_AVAILABLE = True
    except ImportError as e:
        print(f"[Server] ASR routes not available: {e}")
        ASR_ROUTES_AVAILABLE = False


# Initialize FastAPI app
app = FastAPI(
    title="Universal Assistant API",
    description="Universal Assistant LangGraph Python implementation",
    version="0.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Auth middleware: extract user_id from Authorization: Bearer <JWT>
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    try:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        user_id = None
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            if token:
                try:
                    import jwt  # PyJWT
                    secret = getattr(settings, "jwt_secret", None) or ""
                    payload = jwt.decode(token, secret, algorithms=["HS256"])  # type: ignore
                    sub = payload.get("sub")
                    if isinstance(sub, str) and len(sub) > 0:
                        user_id = sub
                except Exception:
                    pass
        request.state.user_id = user_id
    except Exception:
        request.state.user_id = None
    response = await call_next(request)
    return response

# Include document routes if available
if DOCUMENT_ROUTES_AVAILABLE:
    app.include_router(document_router)
    print("[Server] Document processing routes registered")

if WEBSEARCH_ROUTES_AVAILABLE:
    app.include_router(websearch_router)
    print("[Server] Websearch routes registered")

if ASR_ROUTES_AVAILABLE and getattr(settings, "enable_voice", False):
    app.include_router(asr_router)
    print("[Server] ASR routes registered")

# Warmup intent router on startup (non-blocking if disabled)
@app.on_event("startup")
def warmup_intent_router():
    try:
        from ..intent.manager import warmup as _intent_warmup  # type: ignore
        ok = _intent_warmup()
        print(f"[startup] intent router warmup: {ok}")
    except Exception as e:
        print(f"[startup] intent warmup skipped: {e}")

# Initialize Async Postgres checkpointer at startup (optional)
@app.on_event("startup")
async def init_async_checkpointer():
    try:
        dsn = getattr(settings, "pg_dsn", None)
        if not dsn:
            return
        try:
            from ..core.auto_reconnect_checkpointer import AutoReconnectCheckpointer
            from ..core.checkpointer_adapter import MinimalCheckpointerAdapter  # 恢复使用
        except Exception as e:
            print(f"[startup] AutoReconnect/Adapter import failed: {e}")
            return
        # Build an auto-reconnecting saver and pre-connect to ensure setup()
        auto = AutoReconnectCheckpointer(dsn, max_retry=3, connection_max_age=210, setup_on_connect=True)
        try:
            await auto.__aenter__()
            print("[startup] AutoReconnectCheckpointer is connected and ready")
        except Exception as e:
            print(f"[startup] AutoReconnectCheckpointer enter failed: {e}")
            return
        # Wrap with serialization adapter
        saver = MinimalCheckpointerAdapter(auto)  # 使用修复后的 adapter
        # Recompile graph with async checkpointer
        global graph
        graph = create_graph().compile(checkpointer=saver)
        print("[startup] graph compiled with AutoReconnectCheckpointer + MinimalCheckpointerAdapter (fixed)")
        # Ensure proper shutdown cleanup
        async def _shutdown_cm():
            try:
                await auto.__aexit__(None, None, None)
            except Exception:
                pass
        try:
            app.add_event_handler("shutdown", _shutdown_cm)
        except Exception:
            pass
    except Exception as e:
        print(f"[startup] init_async_checkpointer failed: {e}")

# Thread history storage removed; persisted store is the source of truth


def send_sse_event(data: Dict[str, Any], event: str = "message") -> str:
    """Format SSE event"""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def split_token_into_chunks(token: str, max_chunk_size: int = 200) -> List[str]:
    """Split long token into smaller chunks"""
    chunks = []
    current_chunk = ""
    i = 0
    
    while i < len(token):
        current_chunk += token[i]
        i += 1
        
        if len(current_chunk) >= max_chunk_size or i == len(token):
            chunks.append(current_chunk)
            current_chunk = ""
    
    return chunks


@app.post("/api/threads", response_model=ThreadCreateResponse)
async def create_thread(request: Request):
    """Create a new thread"""
    print("[Threads] 收到创建线程请求")
    # Require authenticated user to avoid orphan threads
    req_uid = getattr(request.state, "user_id", None)
    if not req_uid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    thread_id = f"thread_{uuid.uuid4().hex[:8]}"
    print(f"[Threads] 创建新线程: {thread_id}")
    # Persist thread skeleton
    try:
        await ensure_thread(thread_id, req_uid)
    except Exception as e:
        print(f"[Threads] ensure_thread failed: {e}")
    return ThreadCreateResponse(thread_id=thread_id)


@app.post("/api/threads/{thread_id}/runs/stream")
async def stream_response(thread_id: str, request: StreamRequest, http_request: Request):
    """Stream response endpoint"""
    print(f"[Stream] 收到流式请求，线程ID: {thread_id}")
    print(f"[Stream] 输入: {request.input}")
    # 早返回：将线程校验与归属检查移入生成器内部，先发 ACK 减少首字延迟

    # In-memory thread history removed. Persistence is used directly where needed.
    
    async def generate_stream():
        """Generate streaming response"""
        # 🔥 立即打印，确认后端何时收到请求
        print(f"[TIMING] 🎯 后端收到请求！时间: {datetime.now().isoformat()}")
        
        main_message_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        current_content = ""
        has_streamed_content = False
        tool_calls = []
        
        # 使用队列实时推送事件，避免缓冲导致一次性输出
        event_queue: asyncio.Queue[Any] = asyncio.Queue()
        done_sentinel = object()
        
        # 立即发送初始事件
        yield send_sse_event({
            "id": main_message_id,
            "object": "chat.completion.chunk",
            "created": int(datetime.now().timestamp()),
            "model": getattr(settings, "llm_model", "unknown"),
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None
            }]
        }, "message")
        
        # ACK 后再进行线程存在性与归属检查，失败则发送错误并结束
        try:
            try:
                await ensure_thread(thread_id, getattr(http_request.state, "user_id", None))
            except Exception as e:
                print(f"[Stream] ensure_thread failed (post-ack): {e}")
            try:
                owner = await get_thread_owner(thread_id)
                req_uid = getattr(http_request.state, "user_id", None)
                if owner is None or owner != req_uid:
                    raise HTTPException(status_code=404, detail="Thread not found")
            except HTTPException as he:
                err_msg = getattr(he, 'detail', 'Thread not found')
                yield send_sse_event({"error": err_msg, "type": "HTTPException"}, "error")
                return
            except Exception as e:
                print(f"[Stream] ownership check error (post-ack): {e}")
                yield send_sse_event({"error": "Thread not found", "type": "HTTPException"}, "error")
                return
        except Exception:
            # 安全兜底：若校验流程自身异常，直接结束
            return
        
        try:
            # Prepare messages
            messages = request.input.get("messages", [])
            # 安全清洗：移除指向本地预览端点的 image_url，避免上游下载失败
            try:
                cleaned = []
                for m in messages:
                    mm = dict(m) if isinstance(m, dict) else m
                    content = mm.get('content')
                    if isinstance(content, list):
                        new_parts = []
                        for p in content:
                            if isinstance(p, dict) and p.get('type') == 'image_url':
                                url = ((p.get('image_url') or {}) or {}).get('url') if isinstance(p.get('image_url'), dict) else p.get('image_url')
                                url_str = str(url or '')
                                if 'localhost:3000/api/preview' in url_str or '/api/preview/' in url_str:
                                    # 丢弃该图片部件
                                    continue
                            new_parts.append(p)
                        mm['content'] = new_parts
                    cleaned.append(mm)
                messages = cleaned
            except Exception:
                pass
            if not messages:
                raise HTTPException(status_code=400, detail="No messages provided")
            # Persist last user message (raw payload) if present
            try:
                for msg in reversed(messages):
                    role_or_type = (msg.get('role') or msg.get('type') or '').lower()
                    if role_or_type in ["user", "human"]:
                        await pg_insert_message(thread_id, "user", msg, getattr(http_request.state, "user_id", None))
                        break
            except Exception as e:
                print(f"[Stream] 持久化用户消息失败: {e}")
            
            # Convert to LangChain messages
            lc_messages = []
            for msg in messages:
                # Handle both 'role' and 'type' fields for compatibility
                role_or_type = msg.get('role') or msg.get('type')
                content = msg.get('content', '')
                
                # 处理多模态消息（支持图片识别）
                if isinstance(content, list):
                    # 检查是否包含 image_url（需要多模态模型）
                    has_image = any(
                        isinstance(part, dict) and part.get('type') in ('image_url', 'image')
                        for part in content
                    )
                    
                    if has_image:
                        # 保留多模态结构，直接传给 LLM（用于视觉识别）
                        # LangChain 支持 content 为 list 的格式
                        processed_content = []
                        for part in content:
                            if isinstance(part, dict):
                                part_type = part.get('type', '')
                                if part_type == 'text':
                                    processed_content.append({
                                        "type": "text",
                                        "text": part.get('text', '')
                                    })
                                elif part_type == 'image_url':
                                    # 保留 image_url 结构
                                    processed_content.append({
                                        "type": "image_url",
                                        "image_url": part.get('image_url', {})
                                    })
                                elif part_type == 'image':
                                    # 支持前端直接传 image 字段（转为 image_url 格式）
                                    image_data = part.get('image', '')
                                    if image_data:
                                        processed_content.append({
                                            "type": "image_url",
                                            "image_url": {"url": image_data}
                                        })
                                elif part_type == 'file':
                                    # 文件类型暂时转为文本说明
                                    processed_content.append({
                                        "type": "text",
                                        "text": f"[文件: {part.get('name', '')} ({part.get('contentType', '')})]"
                                    })
                                else:
                                    # 其他未知类型也转为文本
                                    processed_content.append({
                                        "type": "text",
                                        "text": f"[{part_type} 内容]"
                                    })
                        content = processed_content
                    else:
                        # 没有图片，按原逻辑转为纯文本
                        combined_content = []
                        for part in content:
                            if isinstance(part, dict):
                                if part.get('type') == 'text':
                                    combined_content.append(part.get('text', ''))
                                elif part.get('type') == 'file':
                                    combined_content.append(f"[文件: {part.get('name', '')} ({part.get('contentType', '')})]")
                                else:
                                    combined_content.append(f"[{part.get('type', '')} 内容]")
                            else:
                                combined_content.append(str(part))
                        content = "\n\n".join(combined_content)
                
                if role_or_type in ["user", "human"]:
                    lc_messages.append(HumanMessage(content=content))
                elif role_or_type in ["assistant", "ai"]:
                    lc_messages.append(AIMessage(content=content))
                elif role_or_type == "system":
                    lc_messages.append(SystemMessage(content=content))
            
            # 图片预处理：先识别图片内容，转换为文本描述，再进入正常流程
            try:
                if getattr(settings, "enable_vision", True):
                    # 检测是否包含图片
                    has_vision_content = False
                    vision_message_index = -1
                    
                    for idx, msg in enumerate(lc_messages):
                        if isinstance(msg.content, list):
                            has_image = any(
                                isinstance(p, dict) and p.get('type') in ('image_url', 'image')
                                for p in msg.content
                            )
                            if has_image:
                                has_vision_content = True
                                vision_message_index = idx
                                break
                    
                    if has_vision_content and vision_message_index >= 0:
                        print("[Vision] 检测到图片内容，开始视觉识别预处理")
                        
                        from ..core.config import get_chat_llm
                        vision_llm = get_chat_llm(temperature=0.1)
                        
                        msg = lc_messages[vision_message_index]
                        content_parts = msg.content if isinstance(msg.content, list) else []
                        
                        # 提取用户原始问题
                        text_parts = [p.get('text', '') for p in content_parts if isinstance(p, dict) and p.get('type') == 'text']
                        original_question = text_parts[0] if text_parts else '请描述这张图片'
                        
                        # 提取图片部分
                        image_parts = [p for p in content_parts if isinstance(p, dict) and p.get('type') in ('image_url', 'image')]
                        
                        print(f"[Vision] 提取到的图片部分: {len(image_parts)} 个")
                        for idx, img in enumerate(image_parts):
                            print(f"[Vision]   图片 {idx+1}: type={img.get('type')}, keys={list(img.keys())}, 数据长度={len(str(img))}")
                        
                        # 🔑 转换图片格式为 OpenAI 期望的格式
                        normalized_image_parts = []
                        for img in image_parts:
                            if img.get('type') == 'image' and 'image' in img:
                                # 前端格式：{'type': 'image', 'image': 'data:image/png;base64,...'}
                                # 转换为 OpenAI 格式：{'type': 'image_url', 'image_url': {'url': '...'}}
                                image_data = img['image']
                                
                                # 🐛 详细调试
                                print(f"[Vision]   🔍 原始图片数据:")
                                print(f"[Vision]     - 数据类型: {type(image_data)}")
                                print(f"[Vision]     - 数据长度: {len(image_data) if isinstance(image_data, str) else 'N/A'}")
                                print(f"[Vision]     - 前100字符: {image_data[:100] if isinstance(image_data, str) else 'N/A'}")
                                print(f"[Vision]     - 是否 data URI: {image_data.startswith('data:') if isinstance(image_data, str) else False}")
                                
                                normalized_image_parts.append({
                                    "type": "image_url",
                                    "image_url": {"url": image_data}
                                })
                                print(f"[Vision]   ✅ 转换格式: image -> image_url")
                            elif img.get('type') == 'image_url':
                                # 已经是正确格式
                                image_url = img.get('image_url', {})
                                url = image_url.get('url', '') if isinstance(image_url, dict) else ''
                                
                                # 🐛 详细调试
                                print(f"[Vision]   🔍 image_url 数据:")
                                print(f"[Vision]     - URL 类型: {type(url)}")
                                print(f"[Vision]     - URL 长度: {len(url) if isinstance(url, str) else 'N/A'}")
                                print(f"[Vision]     - URL 前100字符: {url[:100] if isinstance(url, str) else 'N/A'}")
                                
                                normalized_image_parts.append(img)
                                print(f"[Vision]   ✅ 格式正确: image_url")
                        
                        # 构造视觉识别消息
                        # 🐛 测试：使用更简单直接的英文提示词（GPT 对英文响应更好）
                        vision_content = [
                            {"type": "text", "text": "What's in this image? Describe everything you can see."},
                        ]
                        vision_content.extend(normalized_image_parts)
                        
                        vision_message = HumanMessage(content=vision_content)
                        
                        # 🐛 打印最终发送的消息结构
                        print("[Vision] 📤 发送给 OpenAI 的消息结构:")
                        print(f"[Vision]   - 消息类型: {type(vision_message)}")
                        print(f"[Vision]   - content 类型: {type(vision_message.content)}")
                        print(f"[Vision]   - content 长度: {len(vision_message.content) if isinstance(vision_message.content, list) else 'N/A'}")
                        if isinstance(vision_message.content, list):
                            for idx, part in enumerate(vision_message.content):
                                print(f"[Vision]   - Part {idx+1}: type={part.get('type') if isinstance(part, dict) else type(part)}")
                                if isinstance(part, dict) and part.get('type') == 'image_url':
                                    url = part.get('image_url', {}).get('url', '') if isinstance(part.get('image_url'), dict) else ''
                                    print(f"[Vision]     - URL 前缀: {url[:50] if url else 'empty'}")
                        
                        # 调用视觉 LLM 识别图片
                        print("[Vision] 🚀 正在调用 OpenAI API...")
                        vision_result = await vision_llm.ainvoke([vision_message])
                        print(f"[Vision] ✅ API 调用完成，响应类型: {type(vision_result)}")
                        image_description = vision_result.content
                        
                        print(f"[Vision] 图片识别完成: {image_description[:150]}...")
                        
                        # 将图片消息替换为文本描述
                        # 格式：[图片内容] + 用户问题
                        new_text_content = f"[用户上传了一张图片，图片内容描述如下]\n{image_description}\n\n[用户的问题]\n{original_question}"
                        
                        # 替换原消息
                        lc_messages[vision_message_index] = HumanMessage(content=new_text_content)
                        
                        print("[Vision] 图片已转换为文本描述，进入正常处理流程")
            
            except Exception as e:
                print(f"[Vision] 图片预处理失败，继续使用原始消息: {e}")
                import traceback
                traceback.print_exc()
            
            # Create graph state
            state = GraphState()
            state.messages = lc_messages
            
            # 将事件推入队列的帮助函数（同步回调可安全调用）
            def push_event(data: Dict[str, Any], event: str = "message"):
                try:
                    event_queue.put_nowait(send_sse_event(data, event))
                except Exception:
                    pass
            
            # Stream callback function
            def stream_callback(token: str, calls: List[Any] = None, event_type: str = None):
                nonlocal current_content, has_streamed_content, tool_calls
                # 轻量观测：仅打印前三个 partial_ai chunk 的预览
                try:
                    if getattr(settings, "debug", False) and token:
                        # 统计：基于当前累计内容粗略估算 chunk 序号
                        approx_chunk_index = max(1, len(current_content) // max(len(token), 1))
                        if approx_chunk_index <= 3:
                            preview = token if len(token) <= 120 else token[:120] + "..."
                            print(f"[SSE] partial_ai idx~{approx_chunk_index} len={len(token)} preview={preview}")
                except Exception:
                    pass
                
                if calls:
                    tool_calls.extend(calls)
                
                if token:
                    current_content += token
                    has_streamed_content = True
                    
                    # Split token into chunks for smoother streaming
                    chunks = split_token_into_chunks(token)
                    for chunk in chunks:
                        # 使用 partial_ai 事件，发送累计内容
                        payload = [{
                            "id": main_message_id,
                            "type": "ai",
                            "content": current_content,
                            "delta": chunk,
                            "tool_calls": calls or tool_calls,
                        }]
                        push_event(payload, "partial_ai")
                
                # 处理特殊事件类型
                if event_type == "on_tool_end":
                    push_event({
                        "message": "工具执行完成",
                        "timestamp": int(datetime.now().timestamp())
                    }, "on_tool_end")
                elif event_type == "tool_result":
                    push_event([{
                        "type": "tool",
                        "id": f"tool-{uuid.uuid4().hex[:8]}",
                        "content": token,
                        "tool_calls": calls or []
                    }], "tool_result")
                elif event_type == "approval_required":
                    # 转发审批事件，前端据此显示确认UI
                    push_event({
                        "thread_id": thread_id,
                        "tool_calls": calls or []
                    }, "approval_required")
            
            # 注册线程级回调（不写入 state，避免序列化）
            try:
                register_stream_callback(thread_id, stream_callback)
            except Exception:
                pass
            
            # 并发执行图：生产者把事件推入队列，当前生成器消费并yield
            async def run_graph_and_finalize():
                try:
                    print(f"[Stream] 开始执行图工作流")
                    # Pass thread_id to checkpointer via config, and into state for callback registry
                    config = {"configurable": {"thread_id": thread_id}}
                    state_payload = state.to_dict()
                    try:
                        state_payload["thread_id"] = thread_id
                    except Exception:
                        pass
                    # 注入 user_id 到图的 state，便于子图（如 KG）传递上下文
                    try:
                        req_uid = getattr(http_request.state, "user_id", None)
                        if req_uid:
                            state_payload["user_id"] = req_uid
                    except Exception:
                        pass
                    # 调试模式：输出逐节点事件；生产默认仍用 ainvoke
                    result = None
                    if os.getenv("DEBUG_GRAPH_EVENTS", "0") == "1":
                        try:
                            try:
                                print("[Phase] debug_events start")
                                push_event({"phase": "debug_events", "status": "start"}, "phase")
                            except Exception:
                                pass
                            async for ev in graph.astream_events(state_payload, config=config, stream_mode="values"):
                                try:
                                    evt = ev.get("event") or ev.get("type") or "unknown"
                                    # 事件对象不一定是 dict（可能是 list/str/其他），做类型守卫
                                    if isinstance(ev, dict):
                                        payload = {k: v for k, v in ev.items() if k not in ()}
                                    else:
                                        payload = {"data": ev}
                                    # 直接透传原始事件（仅调试用）
                                    push_event(payload, "debug")
                                    # LangGraph 通常在 on_end 事件里携带最终输出
                                    if evt == "on_end" and isinstance(ev, dict):
                                        data = ev.get("data") or {}
                                        # 常见结构：{"output": result}
                                        result = data.get("output", data) or None
                                except Exception:
                                    pass
                            try:
                                push_event({"phase": "debug_events", "status": "end"}, "phase")
                                print("[Phase] debug_events end")
                            except Exception:
                                pass
                        except Exception as _e:
                            print(f"[Stream] debug events unavailable: {_e}")
                    if result is None:
                        try:
                            push_event({"phase": "formal", "status": "start"}, "phase")
                            print("[Phase] formal start")
                        except Exception:
                            pass
                        result = await graph.ainvoke(state_payload, config=config)
                    
                    # Final event for OpenAI-style finish
                    if has_streamed_content:
                        push_event({
                            "id": main_message_id,
                            "object": "chat.completion.chunk",
                            "created": int(datetime.now().timestamp()),
                            "model": getattr(settings, "llm_model", "unknown"),
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop"
                            }]
                        }, "message")
                        # 收尾摘要：仅在 debug 时打印一次
                        try:
                            if getattr(settings, "debug", False):
                                last_preview = current_content[-120:] if len(current_content) > 120 else current_content
                                print(f"[SSE] partial_ai done total_len={len(current_content)} last_preview={last_preview}")
                        except Exception:
                            pass
                    
                    # 发送 complete 事件（对象载荷，避免前端按“消息数组”解析）
                    push_event({
                        "id": main_message_id,
                        "type": "complete",
                        "created": int(datetime.now().timestamp())
                    }, "complete")
                    # 阶段结束标记（formal）
                    try:
                        push_event({"phase": "formal", "status": "end"}, "phase")
                        print("[Phase] formal end")
                    except Exception:
                        pass
                    
                    # In-memory history update removed
                    # Persist assistant final message and touch thread
                    try:
                        if has_streamed_content:
                            # Use accumulated content if available
                            payload = {"type": "text", "text": current_content}
                            await pg_insert_message(thread_id, "assistant", payload, getattr(http_request.state, "user_id", None))
                            # Optional verbose logging of final content for cross-checking with frontend
                            try:
                                if os.getenv("LOG_FULL_ASSISTANT_REPLY", "1") == "1":
                                    print(f"[Stream] Final content length: {len(current_content)}")
                                    print(f"[Stream] Final content: {current_content}")
                            except Exception:
                                pass
                        else:
                            # 兜底：无流式内容时，尝试从 result 中提取文本
                            try:
                                text_out = ""
                                if isinstance(result, dict):
                                    text_out = (result.get("final_answer") or "")
                                    if not text_out:
                                        msgs = result.get("messages") or []
                                        if isinstance(msgs, list) and len(msgs) > 0:
                                            last = msgs[-1]
                                            try:
                                                text_out = getattr(last, 'content', '') or ''
                                            except Exception:
                                                text_out = str(last)
                                if text_out:
                                    if os.getenv("LOG_FULL_ASSISTANT_REPLY", "1") == "1":
                                        preview = text_out if len(text_out) <= 500 else text_out[:500] + "..."
                                        print(f"[Stream] Fallback content length: {len(text_out)}")
                                        print(f"[Stream] Fallback content preview: {preview}")
                                    await pg_insert_message(thread_id, "assistant", {"type": "text", "text": text_out}, getattr(http_request.state, "user_id", None))
                                else:
                                    print("[Stream] No streamed content and no text found in result; skip persist")
                            except Exception as _e_fb:
                                print(f"[Stream] fallback persist failed: {_e_fb}")
                        await pg_touch_thread(thread_id, getattr(http_request.state, "user_id", None))
                    except Exception as e:
                        print(f"[Stream] 持久化助手消息/更新线程失败: {e}")

                    # 正常完成：通知消费循环结束
                    try:
                        await event_queue.put(done_sentinel)
                        print("[Stream] queued done_sentinel (normal)")
                    except Exception:
                        pass
                
                except Exception as e:
                    import traceback
                    err_type = type(e).__name__
                    err_msg = str(e)
                    err_tb = traceback.format_exc()
                    print(f"[Stream] 错误: {err_type}: {err_msg}\n{err_tb}")
                    try:
                        push_event({"error": err_msg, "type": err_type, "trace": err_tb}, "error")
                    except Exception:
                        pass
                    finally:
                        # 异常时也确保通知消费循环结束
                        try:
                            await event_queue.put(done_sentinel)
                        except Exception:
                            pass
            
            producer_task = asyncio.create_task(run_graph_and_finalize())
            
            # 消费并实时返回事件
            while True:
                event_or_sentinel = await event_queue.get()
                if event_or_sentinel is done_sentinel:
                    break
                yield event_or_sentinel
            
            # 确保生产者结束
            try:
                await producer_task
            finally:
                pass
            print(f"[Stream] 流式响应完成")
        except Exception as e:
            import traceback
            err_type = type(e).__name__
            err_msg = str(e)
            err_tb = traceback.format_exc()
            print(f"[Stream] 错误: {err_type}: {err_msg}\n{err_tb}")
            yield send_sse_event({
                "error": err_msg,
                "type": err_type,
                "trace": err_tb
            }, "error")
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, request: Request):
    """Get thread messages"""
    try:
        # Prefer persisted store for auth; in-memory is best-effort and not per-user
        rows = await pg_load_messages(thread_id, getattr(request.state, "user_id", None))
        if rows is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {
            "thread_id": thread_id,
            "messages": rows,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Threads] load messages error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load messages")


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str, request: Request):
    """Delete a thread"""
    try:
        await pg_delete_thread(thread_id, getattr(request.state, "user_id", None))
        # In-memory cache cleanup removed
        return {"message": "Thread deleted successfully"}
    except Exception as e:
        print(f"[Threads] 删除线程失败: {e}")
        raise HTTPException(status_code=404, detail="Thread not found")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Universal Assistant API",
        "version": "0.0.0",
        "status": "running"
    }


@app.post("/api/threads/{thread_id}/tools/approval")
async def approve_tool(thread_id: str, request: Request):
    """Approve or reject a tool execution and optionally execute it.

    Body: { toolName: str, args: dict, approve: bool, toolCallId?: str }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    tool_name = (body or {}).get("toolName")
    args = (body or {}).get("args") or {}
    approve = bool((body or {}).get("approve"))
    tool_call_id = (body or {}).get("toolCallId")

    # Ownership check (same as stream)
    try:
        owner = await get_thread_owner(thread_id)
        req_uid = getattr(request.state, "user_id", None)
        if owner is None or owner != req_uid:
            raise HTTPException(status_code=404, detail="Thread not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[approval] ownership check error: {e}")
        raise HTTPException(status_code=404, detail="Thread not found")

    if not tool_name:
        raise HTTPException(status_code=400, detail="toolName is required")

    # Persist the decision first
    try:
        await pg_insert_message(thread_id, "assistant", {
            "type": "approval_result",
            "approve": approve,
            "toolName": tool_name,
            "args": args,
            **({"toolCallId": tool_call_id} if tool_call_id else {}),
        }, getattr(request.state, "user_id", None))
    except Exception as e:
        print(f"[approval] persist decision failed: {e}")

    if not approve:
        return {"ok": True}

    # Execute tool on approval
    tool = TOOL_BY_NAME.get(tool_name)
    if not tool:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool_name}")

    try:
        result = await tool.ainvoke(args)
        try:
            await pg_insert_message(thread_id, "assistant", {
                "type": "tool_result",
                "toolName": tool_name,
                "args": args,
                "result": result,
            }, getattr(request.state, "user_id", None))
            await pg_touch_thread(thread_id, getattr(request.state, "user_id", None))
        except Exception as e:
            print(f"[approval] persist result failed: {e}")
        return {"ok": True, "result": result}
    except Exception as e:
        print(f"[approval] tool execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    ) 