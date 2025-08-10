"""
FastAPI server for the financial expert backend
"""
import asyncio
import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..core.config import settings
from ..core.graph import graph, GraphState
from ..models.types import ThreadCreateResponse, StreamRequest, Message
from ..tools.registry import ALL_TOOLS_LIST
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


# Initialize FastAPI app
app = FastAPI(
    title="Financial Expert API",
    description="Financial expert LangGraph Python implementation",
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

# Thread history storage
thread_history: Dict[str, List[Message]] = {}


def send_sse_event(data: Dict[str, Any], event: str = "message") -> str:
    """Format SSE event"""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def split_token_into_chunks(token: str, max_chunk_size: int = 10) -> List[str]:
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
async def create_thread():
    """Create a new thread"""
    print("[Threads] 收到创建线程请求")
    thread_id = f"thread_{uuid.uuid4().hex[:8]}"
    thread_history[thread_id] = []
    print(f"[Threads] 创建新线程: {thread_id}")
    return ThreadCreateResponse(thread_id=thread_id)


@app.post("/api/threads/{thread_id}/runs/stream")
async def stream_response(thread_id: str, request: StreamRequest):
    """Stream response endpoint"""
    print(f"[Stream] 收到流式请求，线程ID: {thread_id}")
    print(f"[Stream] 输入: {request.input}")
    
    if thread_id not in thread_history:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    async def generate_stream():
        """Generate streaming response"""
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
            "model": "gpt-4o-mini",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None
            }]
        }, "message")
        
        try:
            # Prepare messages
            messages = request.input.get("messages", [])
            if not messages:
                raise HTTPException(status_code=400, detail="No messages provided")
            
            # Convert to LangChain messages
            lc_messages = []
            for msg in messages:
                # Handle both 'role' and 'type' fields for compatibility
                role_or_type = msg.get('role') or msg.get('type')
                content = msg.get('content', '')
                
                # 处理多模态消息 - 校准TypeScript版本
                if isinstance(content, list):
                    # 多模态消息处理
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
                
                if calls:
                    tool_calls.extend(calls)
                
                if token:
                    current_content += token
                    has_streamed_content = True
                    
                    # Split token into chunks for smoother streaming
                    chunks = split_token_into_chunks(token)
                    for chunk in chunks:
                        # 与TypeScript后端一致：使用 partial_ai 事件，发送累计内容
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
            
            state.stream_callback = stream_callback
            
            # 并发执行图：生产者把事件推入队列，当前生成器消费并yield
            async def run_graph_and_finalize():
                try:
                    print(f"[Stream] 开始执行图工作流")
                    result = await graph.ainvoke(state.to_dict())
                    
                    # Final event for OpenAI-style finish
                    if has_streamed_content:
                        push_event({
                            "id": main_message_id,
                            "object": "chat.completion.chunk",
                            "created": int(datetime.now().timestamp()),
                            "model": "deepseek-chat",
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop"
                            }]
                        }, "message")
                    
                    # 发送complete事件
                    push_event([], "complete")
                    
                    # Update thread history
                    thread_history[thread_id].extend(messages)
                    if result and result.get("messages"):
                        last_message = result["messages"][-1]
                        if hasattr(last_message, 'content'):
                            thread_history[thread_id].append(Message(
                                role="assistant",
                                content=last_message.content
                            ))
                except Exception as e:
                    print(f"[Stream] 错误: {e}")
                    push_event({"error": str(e)}, "error")
                finally:
                    # 通知消费者完成
                    await event_queue.put(done_sentinel)
            
            producer_task = asyncio.create_task(run_graph_and_finalize())
            
            # 消费并实时返回事件
            while True:
                event_or_sentinel = await event_queue.get()
                if event_or_sentinel is done_sentinel:
                    break
                yield event_or_sentinel
            
            # 确保生产者结束
            await producer_task
            print(f"[Stream] 流式响应完成")
        except Exception as e:
            print(f"[Stream] 错误: {e}")
            yield send_sse_event({
                "error": str(e)
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
async def get_thread_messages(thread_id: str):
    """Get thread messages"""
    if thread_id not in thread_history:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    return {
        "thread_id": thread_id,
        "messages": thread_history[thread_id]
    }


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """Delete a thread"""
    if thread_id not in thread_history:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    del thread_history[thread_id]
    return {"message": "Thread deleted successfully"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Financial Expert API",
        "version": "0.0.0",
        "status": "running"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    ) 