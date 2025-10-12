import asyncio
from typing import Dict, Any, List, Optional, Callable, Annotated, TypedDict, Literal
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    BaseMessage, 
    HumanMessage, 
    AIMessage, 
    SystemMessage,
    ToolMessage
)
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.types import Send
from ..core.config import settings
from ..core.config import get_chat_llm
from ..core.config import resolve_llm_config
from ..core.system_prompt import system_message_content
from ..tools.registry import ALL_TOOLS_LIST, TOOL_BY_NAME
from pydantic import BaseModel, Field
import operator
import uuid
import re


# ✅ 自定义 Reducer：支持清空 + 并行安全
# 
# ⚠️ 重要发现（通过实际测试）：
# 官方 operator.add 无法清空旧数据：[] + [旧数据] = [旧数据]
# 
# 根据 Persistence.txt 第186行：
# - 有 reducer 的字段：累加（old + new）
# - 无 reducer 的字段：覆盖（new 替换 old）
#
# 我们需要一个特殊的 reducer，支持：
# 1. 使用 None 作为"清空信号"（由 collect_base_data 发出）
# 2. 使用 [] 表示 no-op（保持现有数据，用于并行节点）
# 3. 使用非空列表进行累加（并行安全）

def clearable_list_reducer_v2(current: Optional[List], update: Any) -> List:
    """
    改进的列表 reducer：支持显式清空信号
    
    - update is None: 清空信号（返回空列表）
    - update is []: no-op（保持当前值，用于并行节点未返回数据的情况）
    - update is [data]: 累加（并行安全）
    """
    if update is None:
        # None = 清空信号（由 collect_base_data 初始化时发出）
        return []
    if current is None:
        # 首次初始化
        return [] if update == [] else (update if isinstance(update, list) else [])
    if isinstance(update, list):
        if not update:
            # 空列表 = no-op（保持当前值）
            return current
        # 非空列表 = 累加
        return current + update
    # 其他类型 = no-op
    return current

# Tools that require human approval before execution (MVP)
APPROVAL_NEEDED_TOOLS = {
    "graphiti_ingest_detect_tool",
    "graphiti_ingest_commit_tool",
}


class AppState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], add_messages]
    intent: Optional[str]
    # Do NOT persist callbacks; use thread_id + registry instead
    thread_id: Optional[str]
    user_id: Optional[str]
    file_id: Optional[str]
    intent_slots: Dict[str, Any] 
    intent_analysis: Dict[str, Any]
    intent_composed: Optional[str]
    suggested_tool: Optional[str]
    # Vector/RAG-related state (transitioning from rag_* to vector_*)
    retrieval_mode: Optional[str]
    retrieval_attempts: Optional[int]
    last_query: Optional[str]
    filters: Dict[str, Any]
    # removed rag_* keys
    vector_candidates: List[Dict[str, Any]]
    vector_confidence: Dict[str, Any]
    rag_decision: Optional[str]
    vector_decision: Optional[str]
    # Planner/Orchestrator state (reducers enable parallel writes)
    plan: Dict[str, Any]
    # ✅ 使用改进的自定义 reducer：支持清空信号 + 并行安全
    # 使用 None 清空，使用 [] 表示 no-op，使用 [data] 累加
    sql_results: Annotated[List[Dict[str, Any]], clearable_list_reducer_v2]
    vec_results: Annotated[List[Dict[str, Any]], clearable_list_reducer_v2]
    kg_results: Annotated[List[Dict[str, Any]], clearable_list_reducer_v2]
    # Subgraph input parameters
    vec_in: Optional[Dict[str, Any]]
    sql_in: Optional[Dict[str, Any]]
    kg_in: Optional[Dict[str, Any]]
    merged: Annotated[List[Dict[str, Any]], clearable_list_reducer_v2]
    final_answer: Optional[str]
    # Barrier for orchestrator fan-out; workers return {"waiting": -1}
    waiting: Annotated[int, operator.add]
    # Planner/Orchestrator staging & routes
    stage_index: int
    agg_route: str
    # Collect phase hint for routing (whether LLM suggested any tool calls)
    candidate_tool_calls: Optional[bool]


class GraphState:
    """State for the LangGraph workflow"""
    
    def __init__(self, messages: List[BaseMessage] = None, intent: Optional[str] = None, stream_callback: Optional[Callable] = None):
        self.messages: List[BaseMessage] = messages or []
        self.intent: Optional[str] = intent
        self.stream_callback: Optional[Callable] = stream_callback
    
    def add_message(self, message: BaseMessage):
        """Add a message to the state"""
        self.messages.append(message)
    
    def get_last_user_message(self) -> Optional[str]:
        """Get the content of the last user message"""
        for message in reversed(self.messages):
            if isinstance(message, HumanMessage):
                return message.content
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for LangGraph"""
        return {
            "messages": self.messages,
            "intent": self.intent,
            # stream_callback is intentionally excluded to keep checkpointer serializable
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GraphState':
        """Create state from dictionary"""
        return cls(
            messages=data.get("messages", []),
            intent=data.get("intent"),
            stream_callback=data.get("stream_callback")
        )
    
    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-like access for LangGraph compatibility"""
        if key == "messages":
            return self.messages
        elif key == "intent":
            return self.intent
        elif key == "stream_callback":
            return self.stream_callback
        else:
            raise KeyError(f"Unknown key: {key}")
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Allow dictionary-like assignment for LangGraph compatibility"""
        if key == "messages":
            self.messages = value
        elif key == "intent":
            self.intent = value
        elif key == "stream_callback":
            self.stream_callback = value
        else:
            raise KeyError(f"Unknown key: {key}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Allow dictionary-like get for LangGraph compatibility"""
        try:
            return self[key]
        except KeyError:
            return default

# ===== SSE callback registry (thread-scoped, non-serializable) =====
STREAM_CALLBACKS: Dict[str, Callable[[str, List[Any], Optional[str]], None]] = {}

def register_stream_callback(thread_id: str, cb: Callable[[str, List[Any], Optional[str]], None]) -> None:
    if thread_id:
        STREAM_CALLBACKS[thread_id] = cb

def call_stream_callback(thread_id: Optional[str], content: str, calls: List[Any] | None = None, event_type: Optional[str] = None) -> None:
    try:
        if not thread_id:
            return
        cb = STREAM_CALLBACKS.get(thread_id)
        if cb:
            cb(content or "", calls or [], event_type)
    except Exception:
        pass


# Initialize LLM via provider-aware factory
llm = get_chat_llm(temperature=0.1)


def log_with_limit(prefix: str, content: Any, limit: int = 500) -> None:
    """Log content with length limit"""
    content_str = str(content) if isinstance(content, str) else str(content)
    if len(content_str) > limit:
        content_str = content_str[:limit] + "..."
    print(f"{prefix}{content_str}")


def is_ai_message(message: BaseMessage) -> bool:
    """Check if message is an AI message"""
    return isinstance(message, AIMessage)


def get_last_user_message(messages: List[BaseMessage]) -> Optional[str]:
    """Get the content of the last user message"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.content
    return None


async def intent_slot_detect(state: dict) -> Dict[str, Any]:
    """Use internal intent module to extract slots/signals and enrich the state. Safe no-op on failure."""
    try:
        messages = state.get('messages', [])
        user_text = get_last_user_message(messages) or ""
        if not user_text:
            return {}
        try:
            from ..intent.manager import get_router  # type: ignore
        except Exception as e:
            print(f"[intent_slot_detect] import failed: {e}")
            return {}
        try:
            router = get_router()
            if not router:
                return {}
            res = router.process(user_text) or {}
            slots = res.get("slots") or {}
            analysis = res.get("analysis") or {}
            composed = res.get("composed") or ""
            print(f"[intent_slot_detect] slots={slots} composed={composed[:60]}...")
            return {
                "intent_slots": slots,
                "intent_analysis": analysis,
                "intent_composed": composed,
            }
        except Exception as e:
            print(f"[intent_slot_detect] process failed: {e}")
            return {}
    except Exception as e:
        print(f"[intent_slot_detect] unexpected error: {e}")
        return {}


async def detect_intent(state: dict) -> Dict[str, str]:
    """Detect user intent (regular conversation or tool usage)"""
    print("[DetectIntent] 开始检测意图")
    
    
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    user_input = get_last_user_message(messages)

    # 规则优先：根据 intent_slot_detect 的 signals 判断是否需要工具
    try:
        signals = (state.get('intent_analysis') or {}).get('signals') or {}
        has_datetime = bool(signals.get('has_datetime'))
        has_location = bool(signals.get('has_location'))
        has_from_to = bool(signals.get('has_from_to'))
        if has_datetime or has_location or has_from_to:
            print("[DetectIntent] rule-based: need tools")
            return {"intent": "tool", "stream_callback": stream_callback}
    except Exception:
        pass
    
    if not user_input:
        print("[DetectIntent] 没有用户输入，返回regular")
        return {"intent": "regular", "stream_callback": stream_callback}
    
    intent_prompt = f"""
    你是一个意图分类专家。需要根据用户输入判断是"常规对话"（可以直接回答，无需工具）还是"需要工具支持"（需要数据支持、日期计算或搜索等）。
    只返回 "regular" 或 "tool"，无需其他说明。
    输入: "{user_input}"
    """
    
    try:
        response = await llm.ainvoke([{"role": "user", "content": intent_prompt}])
        intent = "tool" if response.content.strip().lower() == "tool" else "regular"
        print(f"[DetectIntent] 检测到用户意图: {intent}，输入: {user_input}")
        return {"intent": intent, "stream_callback": stream_callback}
    except Exception as e:
        print(f"[DetectIntent] 意图检测失败: {e}")
        return {"intent": "regular", "stream_callback": stream_callback}


async def collect_base_data(state: dict) -> Dict[str, Any]:
    """Collect base data for regular conversation
    
    ✅ 官方最佳实践：在新 invocation 开始时初始化状态
    根据 parallel_solution.txt 第67行："状态的重置通常在新的 invocation 中自然发生"
    """
    intent = state.get('intent')
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    
    # ✅ 初始化：使用 None 作为清空信号
    # 
    # 重要：使用改进的 clearable_list_reducer_v2：
    # - None = 清空信号（清除旧数据）
    # - [] = no-op（保持现有数据，并行安全）
    # - [data] = 累加（正常数据累加）
    #
    # 这样做的好处：
    # 1. 明确的清空语义（None vs []）
    # 2. 并行安全（子图返回 [] 不会清空其他子图的数据）
    # 3. 每次新的对话都从干净的状态开始
    init_data = {
        "sql_results": None,  # 清空信号
        "vec_results": None,  # 清空信号
        "kg_results": None,  # 清空信号
        "merged": None,  # 清空信号
    }
    
    if settings.debug:
        print(f"[CollectBaseData] 开始收集基础数据，意图: {intent}")
        print(f"[CollectBaseData] stream_callback 类型: {type(stream_callback)}")
        print(f"[CollectBaseData] 已初始化状态：清空 sql_results, vec_results, kg_results, merged")
    
    # 视觉优先短路：若本轮已完成视觉识别，则直接按 regular 路径生成回答
    try:
        if bool(state.get("vision_processed")):
            intent = "regular"
    except Exception:
        pass

    if intent == "regular":
        now = datetime.now()
        # 若已完成视觉转写，追加一次性规则，避免模型输出“无法查看图片”等措辞
        vision_note = ""
        try:
            if bool(state.get("vision_processed")):
                vision_note = "\n【视觉说明】本轮已完成图片转写；请仅基于下述描述直接回答，避免出现‘无法查看图片’、‘抱歉无法查看图片’等措辞。"
        except Exception:
            pass
        updated_system_message = SystemMessage(
            content=(
                f"{system_message_content.content} 以当前时间 {now} 作为分析起点。\n"
                f"基于以下用户槽位概要进行回答（不可杜撰）：{(state.get('intent_composed') or '') if state.get('intent_composed') else '无'}\n"
                f"可参考槽位字段：{state.get('intent_slots') or {}}"
                f"{vision_note}"
            )
        )
        
        # Prepare messages for streaming
        messages_for_llm = [updated_system_message] + messages
        
        if settings.debug:
            print("[CollectBaseData] 开始流式生成常规对话回复")
        
        full_content = ""
        chunk_count = 0
        
        try:
            async for chunk in llm.astream(messages_for_llm):
                content = getattr(chunk, 'content', '') or ''
                if not content:
                    continue
                
                chunk_count += 1
                full_content += content
                # 降噪：仅在调试时、首3块与每20块打印一次
                if settings.debug and (chunk_count <= 3 or (chunk_count % 20 == 0)):
                    print(f"[CollectBaseData] 收到chunk {chunk_count}")
                
                # 通过线程级回调推送，不写日志
                try:
                    call_stream_callback(state.get('thread_id'), content, [], "partial_ai")
                except Exception:
                    pass
            
            result_message = AIMessage(content=full_content)
            log_with_limit("常规对话回复: ", full_content, 300)
            
            # 标记已完成流式，避免后续 simple_response 再次生成
            return {
                **init_data,
                "messages": [result_message],
                "intent": intent,
                "already_streamed": True
            }
            
        except Exception as e:
            error_message = AIMessage(content=f"抱歉，生成回复时出现错误: {str(e)}")
            return {
                **init_data,
                "messages": [error_message],
                "intent": intent
            }
    
    # 工具调用逻辑（intent == "tool" 分支：仅探测，不流式输出，不产出可见AI文本）
    now = datetime.now()
    updated_system_message = SystemMessage(
        content=(
            f"{system_message_content.content} 当前时间是 {now.strftime('%Y-%m-%d %H:%M:%S')}。\n"
            f"用户槽位概要：{(state.get('intent_composed') or '') if state.get('intent_composed') else '无'}\n"
            f"槽位字段：{state.get('intent_slots') or {}}\n"
            f"请仅选择一个最相关的工具调用（如日期计算/数据库查询/向量搜索），并严格构造该工具的参数；如无需工具则直接回答。"
        )
    )
    
    try:
        # 绑定工具到LLM并调用
        llm_with_tools = llm.bind_tools(ALL_TOOLS_LIST)
        result = await llm_with_tools.ainvoke([updated_system_message] + messages)
        
        has_calls = False
        tool_names: List[str] = []
        if hasattr(result, 'tool_calls') and result.tool_calls and len(result.tool_calls) > 0:
            has_calls = True
            try:
                tool_names = [getattr(tc, 'name', None) for tc in result.tool_calls]
            except Exception:
                tool_names = []
            # 命中人工确认白名单则拦截执行，先发起审批事件
            try:
                needs_approval = any((getattr(tc, 'name', None) in APPROVAL_NEEDED_TOOLS) for tc in result.tool_calls)
            except Exception:
                needs_approval = False
            if needs_approval:
                try:
                    call_stream_callback(state.get('thread_id'), "", result.tool_calls, "approval_required")
                except Exception:
                    pass
                return {
                    **init_data,
                    "messages": [AIMessage(content="检测到需要数据入库的操作，已发起人工确认，请在界面中确认或取消。")],
                    "intent": intent,
                }

        # 不流式、不回写AI文本；仅记录是否存在候选工具调用以用于后续路由
        if has_calls:
            return {
                **init_data,
                "intent": intent,
                "candidate_tool_calls": True,
                "tool_candidates": tool_names
            }
        print("[CollectBaseData] 无工具候选，改走 simple_response（LLM 未建议可执行 tool_calls）")
        return {
            **init_data,
            "intent": intent,
            "candidate_tool_calls": False,
            "tool_candidates": []
        }
        
    except Exception as e:
        print(f"[CollectBaseData] 工具调用失败: {e}")
        error_message = AIMessage(content=f"抱歉，工具调用时出现错误: {str(e)}")
        return {
            **init_data,
            "messages": [error_message],
            "intent": intent
        }


async def plan_node(state: dict) -> Dict[str, Any]:
    """Planner: 产出结构化 plan（支持 stages/parallel/fast_path/when）。"""
    try:
        # args 是动态字段，不同 call 类型有不同参数结构
        class _StepModel(BaseModel):
            call: Literal["sql", "vec", "kg"]
            args: dict = Field(default_factory=dict, description="Arguments for the call")
            when: Optional[bool] = True

        class _StageModel(BaseModel):
            parallel: bool = False
            steps: List[_StepModel] = Field(default_factory=list)

        class _PlanModel(BaseModel):
            stages: List[_StageModel] = Field(default_factory=list)
            fast_path: bool = False
            # rationale 字段已移除，以避免 LLM 在复杂嵌套结构中出现格式错误
            # 可通过日志中的 plan 内容推断决策理由

        user_text = get_last_user_message(state.get("messages", [])) or ""
        
        # 获取意图槽位信息作为规划上下文
        intent_slots = state.get('intent_slots') or {}
        intent_composed = state.get('intent_composed') or ""
        intent_context = ""
        if intent_composed:
            intent_context = f"\n用户意图概要：{intent_composed}"
        if intent_slots:
            intent_context += f"\n提取的槽位：{intent_slots}"
        
        # 诊断日志：显示planner接收到的上下文
        print(f"[Planner][Input] user_text: {user_text[:100]}")
        if intent_composed:
            print(f"[Planner][Context] intent_composed: {intent_composed[:100]}")
        if intent_slots:
            print(f"[Planner][Context] intent_slots: {intent_slots}")
        print(f"[Planner][Context] Available state keys: {list(state.keys())}")
        
        # 检查是否有残留的历史数据
        old_merged = state.get("merged", [])
        old_sql = state.get("sql_results", [])
        old_vec = state.get("vec_results", [])
        old_kg = state.get("kg_results", [])
        if old_merged or old_sql or old_vec or old_kg:
            print(f"[Planner][WARNING] Found stale data in state: merged={len(old_merged) if isinstance(old_merged, list) else 'N/A'}, sql={len(old_sql) if isinstance(old_sql, list) else 'N/A'}, vec={len(old_vec) if isinstance(old_vec, list) else 'N/A'}, kg={len(old_kg) if isinstance(old_kg, list) else 'N/A'}")
        
        sys = SystemMessage(content=(
            "你是任务规划器。根据用户意图生成一个调用数据源的计划。\n"
            "\n"
            "【可用数据源】\n"
            "1. sql - 查询结构化业务数据\n"
            "   - 数据库 'business' 包含 order 表（订单信息）\n"
            "   - 字段包括：order_id, uid, province, city, total_price, pay_price, pay_time, create_time, status 等\n"
            "   - 适用场景：查询订单、统计销售额、分析用户购买行为、地区分布等\n"
            "   - args 格式（必须是结构化对象）：\n"
            "     * 简单查询：{\"table\": \"order\", \"fields\": [\"order_id\", \"pay_price\", \"create_time\"], \"limit\": 10}\n"
            "     * 带条件：{\"table\": \"order\", \"fields\": [\"*\"], \"conditions\": {\"status\": {\"eq\": 1}}, \"limit\": 10}\n"
            "     * 按时间排序：{\"table\": \"order\", \"fields\": [\"*\"], \"order_by\": [{\"field\": \"create_time\", \"direction\": \"DESC\"}], \"limit\": 10}\n"
            "\n"
            "2. vec - 搜索已上传的文档和知识库\n"
            "   - 支持的文档类别：finance(金融)、ai(人工智能)、blockchain(区块链)、robotics(机器人)、technology(科技)、general(通用)\n"
            "   - 适用场景：搜索文档内容、查找知识库信息、语义检索\n"
            "   - args 示例：{\"query\": \"搜索关键词\", \"limit\": 5}\n"
            "\n"
            "3. kg - 知识图谱查询\n"
            "   - 适用场景：实体关系查询、图谱搜索\n"
            "   - args 示例：{\"type\": \"graph.search\", \"args\": {\"query\": \"关键词\", \"limit\": 5}}\n"
            "\n"
            "【规划原则】\n"
            "- 根据用户问题选择最合适的数据源（订单/销售/业务数据→sql；文档/知识→vec；关系图谱→kg）\n"
            "- 可以组合多个数据源：设置 parallel: true 表示并行执行，parallel: false 表示顺序执行\n"
            "- when 字段可省略，默认为 true\n"
            "\n"
            "【输出结构示例】\n"
            "单数据源：\n"
            "{\"stages\": [{\"parallel\": false, \"steps\": [{\"call\": \"sql\", \"args\": {...}}]}]}\n"
            "\n"
            "多数据源并行：\n"
            "{\"stages\": [{\"parallel\": true, \"steps\": [{\"call\": \"sql\", \"args\": {...}}, {\"call\": \"vec\", \"args\": {...}}]}]}\n"
            "\n"
            "多数据源顺序：\n"
            "{\"stages\": [{\"steps\": [{\"call\": \"sql\", \"args\": {...}}]}, {\"steps\": [{\"call\": \"vec\", \"args\": {...}}]}]}"
            f"{intent_context}"
        ))

        # 选择结构化方法（支持自动降级）
        method = settings.structured_planner_method or "auto"
        provider = settings.llm_provider or "deepseek"

        # 以 resolve_llm_config 的解析结果为准，避免被环境中的 LLM_MODEL 误导
        resolved_model = ""
        resolved_base_url = ""
        try:
            cfg = resolve_llm_config()
            resolved_model = (cfg.get("model") or "")
            resolved_base_url = (cfg.get("base_url") or "")
        except Exception as _e:
            # Fallback：根据 provider 使用对应的配置字段
            if provider == "deepseek":
                resolved_model = settings.deepseek_model or ""
                resolved_base_url = settings.deepseek_base_url or ""
            else:
                resolved_model = settings.openai_model or ""
                resolved_base_url = settings.openai_base_url or ""
        try:
            print(f"[Planner][Probe] provider={provider} resolved_model={resolved_model} base_url={resolved_base_url}")
        except Exception:
            pass

        # Provider-strict：直接按提供商选择唯一方法
        # deepseek -> json_mode；openai/azure -> json_schema；其他 -> json_mode
        chosen_method = "json_mode" if provider not in ("openai", "azure") else "json_schema"
        try:
            print(f"[Planner][Probe] chosen_method={chosen_method}")
        except Exception:
            pass

        def _log_choice(tag: str):
            try:
                print(f"[Planner] method={tag} provider={provider} resolved_model={resolved_model}")
            except Exception:
                pass

        async def _try_json_schema() -> Dict[str, Any]:
            _log_choice("json_schema")
            # OpenAI Structured Outputs 不支持动态 args（需要 additionalProperties: false）
            # 使用 function_calling 方法以支持动态字段
            structured = llm.with_structured_output(_PlanModel, method="function_calling")
            res = await structured.ainvoke([sys, HumanMessage(content=user_text)])
            plan = res.model_dump()
            return {"plan": plan, "stage_index": 0}

        async def _try_json_mode() -> Dict[str, Any]:
            _log_choice("json_mode")
            json_llm = llm.bind(
                response_format={"type": "json_object"},
                temperature=0,
                top_p=0.1,
                stream=False,
                max_tokens=500,  # 降低token限制，确保输出简洁
            )
            # DeepSeek 的 JSON Mode 需要提示中包含 "json" 并明确只输出 JSON
            schema = _PlanModel.model_json_schema()
            json_hint = (
                "请严格以json格式输出（仅输出JSON，不要任何额外文本；不要使用markdown代码块标记如```），并确保输出满足以下JSON Schema：\n"
                f"{schema}\n"
                "对各步骤的 args 约定如下：\n"
                "- 当 call=\"kg\" 时，args 必须为对象，且包含字段：{type: string, args: object}。\n"
                "  * 搜索示例：{\"type\":\"graph.search\", \"args\":{\"query\":\"关键词\", \"limit\":5}}\n"
                "  * 写入示例：{\"type\":\"graph.write.entity\", \"args\":{...}} 或 graph.write.edge / graph.write.episode\n"
            )
            msg = await json_llm.ainvoke([SystemMessage(content=json_hint), sys, HumanMessage(content=user_text)])
            content = getattr(msg, "content", "") or ""
            try:
                print(f"[Planner][RAW] {content[:300]}")
            except Exception:
                pass
            plan_obj = _PlanModel.model_validate_json(content)
            plan_dict = plan_obj.model_dump()
            
            try:
                stages = plan_dict.get("stages") or []
                first = stages[0] if stages else {}
                steps = (first.get("steps") or []) if isinstance(first, dict) else []
                calls_preview = [s.get("call") for s in steps if isinstance(s, dict)]
                print(f"[Planner][PlanSummary] stages={len(stages)} stage0.parallel={bool(first.get('parallel') if isinstance(first, dict) else False)} stage0.calls={calls_preview}")
                # 详细日志：显示每个step的args（前50个字符）
                for idx, step in enumerate(steps, 1):
                    if isinstance(step, dict):
                        args_str = str(step.get("args", {}))[:50]
                        print(f"[Planner][Step{idx}] call={step.get('call')} args={args_str}...")
                if getattr(settings, 'trace_events', False):
                    try:
                        call_stream_callback(state.get('thread_id'), plan_dict, [], "plan_ready")
                    except Exception:
                        pass
            except Exception:
                pass
            return {"plan": plan_dict, "stage_index": 0}

        async def _try_tool_calling() -> Dict[str, Any]:
            _log_choice("tool_calling")
            schema = _PlanModel.model_json_schema()
            tools = [{
                "type": "function",
                "function": {
                    "name": "submit_plan",
                    "description": "Return the multi-stage plan",
                    "parameters": schema,
                },
            }]
            forced = {"type": "function", "function": {"name": "submit_plan"}}
            fc_llm = llm.bind(tools=tools, tool_choice=forced)
            resp = await fc_llm.ainvoke([sys, HumanMessage(content=user_text)])
            # 兼容多种返回结构
            args_json = None
            try:
                calls = getattr(resp, "tool_calls", None) or resp.additional_kwargs.get("tool_calls")  # type: ignore
            except Exception:
                calls = None
            if calls and len(calls) > 0:
                fn = calls[0].get("function") or {}
                args_json = fn.get("arguments")
            if not args_json:
                raise ValueError("No tool_calls/arguments in planner response")
            plan_obj = _PlanModel.model_validate_json(args_json)
            return {"plan": plan_obj.model_dump(), "stage_index": 0}

        # Provider-strict 执行，随后做可执行性校验
        try:
            if chosen_method == "json_schema":
                out = await _try_json_schema()
            else:
                out = await _try_json_mode()
            # 可执行性校验：必须至少一个 stage，且首个 stage 在 when 过滤后至少一个 step
            try:
                plan_dict = out.get("plan") or {}
                stages = plan_dict.get("stages") or []
                if not stages:
                    print("[Planner] empty stages → retry with explicit instruction")
                    raise ValueError("empty_plan")
                first = stages[0] or {}
                raw_steps = first.get("steps") or []
                exec_steps = [s for s in raw_steps if (s.get("when", True) is not False)]
                if not exec_steps:
                    print("[Planner] no executable steps in first stage → retry")
                    raise ValueError("no_executable_steps")
            except Exception as _e_check:
                # 触发外层异常处理
                raise _e_check
            # ✅ 官方最佳实践：不在节点中清空列表
            # 根据 parallel_solution.txt 第68行："状态的重置通常在新的 invocation 中自然发生"
            # 使用 operator.add 作为 reducer 时，返回空列表不会覆盖已有数据（old + [] = old）
            print(f"[Planner] Plan generated successfully")
            return out
        except Exception as e:
            print(f"[Planner] Planning failed: {e}")
            # 不再自动 fallback，而是返回错误并给出明确提示
            print(f"[Planner] Planner could not generate a valid plan. User text: {user_text[:100]}")
            raise  # 向外传播异常，由外层统一处理
    except Exception as e:
        print(f"[Planner] Outer exception handler: {e}")
        # 根据用户查询内容智能选择 fallback 数据源
        user_text = get_last_user_message(state.get("messages", [])) or ""
        
        # 关键词匹配来选择合适的数据源
        sql_keywords = ["订单", "销售", "购买", "金额", "价格", "支付", "用户", "统计", "分析", "查询", "数据库"]
        vec_keywords = ["文档", "搜索", "查找", "知识", "资料", "内容", "检索"]
        kg_keywords = ["关系", "图谱", "实体", "知识图谱"]
        
        user_text_lower = user_text.lower()
        
        # 优先级判断
        if any(kw in user_text for kw in sql_keywords):
            fallback_call = "sql"
            # 使用简单查询格式：查询 order 表的所有字段，按创建时间倒序，限制10条
            fallback_args = {
                "table": "order",
                "fields": ["*"],
                "order_by": [{"field": "create_time", "direction": "DESC"}],
                "limit": 10
            }
            print(f"[Planner] Fallback to SQL based on keywords")
        elif any(kw in user_text for kw in kg_keywords):
            fallback_call = "kg"
            fallback_args = {"type": "graph.search", "args": {"query": user_text, "limit": 5}}
            print(f"[Planner] Fallback to KG based on keywords")
        else:
            # 默认使用 vec（文档搜索）
            fallback_call = "vec"
            fallback_args = {"query": user_text, "limit": 5}
            print(f"[Planner] Fallback to VEC (default)")
        
        fallback = {
            "stages": [
                {"parallel": False, "steps": [{"call": fallback_call, "args": fallback_args}]}
            ],
            "fast_path": False
        }
        print(f"[Planner] Fallback plan: {fallback}")
        # 同时清空历史数据
        return {
            "plan": fallback,
            "stage_index": 0,
            "sql_results": [],
            "vec_results": [],
            "kg_results": [],
            "merged": []
        }


def _detect_simple_date_tool_call(messages: List[BaseMessage]) -> Optional[dict]:
    """Heuristic fallback: detect queries like '上周X是什么时间' and build a date_calculator_tool call."""
    user_text = get_last_user_message(messages) or ""
    match = re.search(r"上周([一二三四五六日天])", user_text)
    if not match:
        return None
    weekday_map = {
        "一": "monday",
        "二": "tuesday",
        "三": "wednesday",
        "四": "thursday",
        "五": "friday",
        "六": "saturday",
        "日": "sunday",
        "天": "sunday",
    }
    wd_cn = match.group(1)
    weekday = weekday_map.get(wd_cn)
    if not weekday:
        return None
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "name": "date_calculator_tool",
        "args": {
            "base_date": "today",
            "operations": [{"type": "previous_weekday", "value": weekday}]
        }
    }


async def vector_prepare(state: dict) -> Dict[str, Any]:
    # 从 vec_in 中提取查询参数，如果不存在则从 messages 中获取
    vec_in = state.get('vec_in', {})
    query_from_vec_in = vec_in.get('query', '') if isinstance(vec_in, dict) else ''
    
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    user_text = query_from_vec_in or get_last_user_message(messages) or ""
    # Default to fast; can be overridden by intent signals or upstream settings
    retrieval_mode = 'fast'
    filters: Dict[str, Any] = {}
    try:
        analysis = state.get('intent_analysis') or {}
        signals = analysis.get('signals') or {}
        if signals.get('has_datetime'):
            filters['has_datetime'] = True
        # If intent indicates evidence/citation requirement, prefer precise
        need_citation = bool(signals.get('need_citation') or signals.get('need_evidence'))
        if need_citation:
            retrieval_mode = 'precise'
    except Exception:
        pass
    if stream_callback:
        try:
            stream_callback(f"[Vector] 模式: {retrieval_mode}", [], "partial_ai")
        except Exception:
            pass
    return {
        "retrieval_mode": retrieval_mode,
        "retrieval_attempts": 0,
        "last_query": user_text,
        "filters": filters,
    }


def _normalize_evidence_from_result(result: Any, source: str) -> List[Dict[str, Any]]:
    evidences: List[Dict[str, Any]] = []
    try:
        if not result:
            return evidences
        if isinstance(result, dict) and 'data' in result and isinstance(result['data'], list):
            for r in result['data']:
                evidences.append({
                    "text": r.get("text", ""),
                    "score": r.get("score", 0.0),
                    "metadata": r.get("metadata", {}),
                    "source": source,
                })
            return evidences
        if isinstance(result, dict) and 'results' in result and isinstance(result['results'], list):
            for r in result['results']:
                evidences.append({
                    "text": r.get("text", r.get("snippet", "")),
                    "score": r.get("score", 0.0),
                    "metadata": r.get("metadata", {}),
                    "source": source,
                })
            return evidences
        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict):
                    evidences.append({
                        "text": r.get("text", ""),
                        "score": r.get("score", 0.0),
                        "metadata": r.get("metadata", {}),
                        "source": source,
                    })
    except Exception:
        pass
    return evidences


async def vector_fetch_evidence(state: dict) -> Dict[str, Any]:
    stream_callback = state.get('stream_callback')
    retrieval_mode = state.get('retrieval_mode') or 'fast'
    
    # 优先使用 last_query（改写后的），然后是 vec_in，最后是 messages
    vec_in = state.get('vec_in', {})
    query = state.get('last_query') or ""
    if not query:
        query_from_vec_in = vec_in.get('query', '') if isinstance(vec_in, dict) else ''
        query = query_from_vec_in or get_last_user_message(state.get('messages', [])) or ""
    
    # 从 vec_in 获取 limit，如果没有则使用默认的 RAG 配置
    limit_from_vec_in = vec_in.get('limit') if isinstance(vec_in, dict) else None
    if limit_from_vec_in and isinstance(limit_from_vec_in, (int, float)) and limit_from_vec_in > 0:
        top_k = int(limit_from_vec_in)
    else:
        top_k = settings.rag_top_k_fast if retrieval_mode == 'fast' else settings.rag_top_k_precise
    
    # 确定查询来源用于日志
    from_last_query = bool(state.get('last_query'))
    from_vec_in = not from_last_query and bool(vec_in.get('query') if isinstance(vec_in, dict) else False)
    from_messages = not from_last_query and not from_vec_in
    
    evidences: List[Dict[str, Any]] = []
    used_source = None
    try:
        # 数据检索过程对用户透明，不发送前端通知
        tool = TOOL_BY_NAME.get('search_documents_tool')
        print(f"[Vector] Tool found: {tool is not None}")
        
        if tool:
            print(f"[Vector] About to call search_documents_tool with query='{query}' limit={top_k} user_id={state.get('user_id')}")
            res = await tool.ainvoke({
                "query": query,
                "categories": None,
                "filename": None,
                "limit": top_k,
                "user_id": state.get("user_id"),
            })
            evidences = _normalize_evidence_from_result(res, 'vector')
            used_source = 'vector'
            # ✅ 添加详细日志（对齐SQL格式）
            print(f"[Vector] Tool returned {len(evidences)} evidence items")
            if evidences:
                print(f"[Vector] First evidence sample: text={evidences[0].get('text', '')[:100]}... score={evidences[0].get('score')}")
            print(f"[Vector] Total evidences to process: {len(evidences)}")
        else:
            print(f"[Vector] ERROR: search_documents_tool not found in TOOL_BY_NAME!")
            print(f"[Vector] Available tools: {list(TOOL_BY_NAME.keys())}")
    except Exception as e:
        print(f"[Vector] fetch_evidence error: {e}")
    # 数据通过 state.vector_candidates 传递，无需前端通知
    # 覆盖式写入，避免累加重复
    return {"vector_candidates": evidences, "retrieval_mode": retrieval_mode}


def _compute_confidence(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return {"hits": 0, "top1": 0.0, "avg": 0.0, "margin": 0.0}
    scores = [float(c.get("score", 0.0) or 0.0) for c in candidates]
    scores_sorted = sorted(scores, reverse=True)
    top1 = scores_sorted[0]
    top2 = scores_sorted[1] if len(scores_sorted) > 1 else 0.0
    avg = sum(scores) / max(len(scores), 1)
    return {"hits": len(candidates), "top1": top1, "avg": avg, "margin": top1 - top2}


async def vector_assess(state: dict) -> Dict[str, Any]:
    stream_callback = state.get('stream_callback')
    candidates: List[Dict[str, Any]] = state.get('vector_candidates') or []
    attempts = int(state.get('retrieval_attempts') or 0)
    metrics = _compute_confidence(candidates)
    
    # Simplified low-confidence rule: hits == 0 or top1 < threshold
    low = (
        metrics.get('hits', 0) == 0 or
        metrics.get('top1', 0.0) < settings.rag_min_score
    )
    
    decision = "answer"
    if low and attempts < settings.rag_attempts_max:
        decision = "rewrite"
    elif low:
        decision = "fallback"
        
    if stream_callback:
        try:
            stream_callback(f"[Vector] 评估: hits={metrics.get('hits')} top1={metrics.get('top1'):.3f} decision={decision}", [], "partial_ai")
        except Exception:
            pass
            
    return {"vector_confidence": metrics, "vector_decision": decision}


async def vector_rewrite(state: dict) -> Dict[str, Any]:
    attempts = int(state.get('retrieval_attempts') or 0)
    query = state.get('last_query') or get_last_user_message(state.get('messages', [])) or ""
    
    prompt = (
        "请对以下查询进行改写，使其更明确、包含可能的同义词或关键实体，便于检索得到更高召回率。\n"
        "仅输出改写后的查询文本：\n"
        f"原始查询：{query}"
    )
    try:
        resp = await llm.ainvoke([{"role": "user", "content": prompt}])
        rewritten = (resp.content or "").strip() or query
    except Exception as e:
        print(f"[Vector][Rewrite] LLM rewrite failed: {e}")
        rewritten = query
        
    return {
        "last_query": rewritten,
        "retrieval_mode": "precise",
        "retrieval_attempts": attempts + 1,
    }


async def vector_answer(state: dict) -> Dict[str, Any]:
    stream_callback = state.get('stream_callback')
    messages = state.get('messages', [])
    candidates: List[Dict[str, Any]] = state.get('vector_candidates') or []
    top_evs = candidates[: min(8, len(candidates))]
    context_lines = []
    for idx, ev in enumerate(top_evs, start=1):
        text = ev.get("text", "")
        context_lines.append(f"[{idx}] {text}")
    context = "\n".join(context_lines)
    sys = SystemMessage(content=(
        f"你是严谨的助手。仅基于下列证据直接回答用户问题，必要时引用编号如[1][2]。\n"
        f"禁止输出以下内容：工具列表、工具/函数/JSON 结构、代码片段、能力边界/限制声明、让用户去运行代码或调用API的建议。\n"
        f"若证据不足，只能明确说明‘证据不足’，不得虚构或建议外部操作。\n"
        f"只输出最终回答文本。\n"
        f"证据：\n{context}"
    ))
    full_content = ""
    try:
        async for chunk in llm.astream([sys] + messages):
            content = getattr(chunk, 'content', '') or ''
            if not content:
                continue
            full_content += content
            if stream_callback:
                stream_callback(content, [], "partial_ai")
        result_message = AIMessage(content=full_content)
        # 输出 vec_results 供父级聚合，并减小并发栅栏
        # ✅ 添加详细日志（对齐SQL格式）
        print(f"[Vector] Returning to parent: vec_results with {len(top_evs)} items, waiting=-1")
        if top_evs:
            print(f"[Vector] First result sample: text={top_evs[0].get('text', '')[:100]}... score={top_evs[0].get('score')}")
        return {"messages": [result_message], "vec_results": top_evs, "waiting": -1}
    except Exception as e:
        print(f"[Vector] answer error: {e}")
        return {"messages": [AIMessage(content="抱歉，生成回答时发生错误。")] , "vec_results": [], "waiting": -1}


async def vector_fallback(state: dict) -> Dict[str, Any]:
    stream_callback = state.get('stream_callback')
    fallback_msg = "当前检索命中不足。我可以尝试网络检索或请你补充更具体的信息。"
    if stream_callback:
        try:
            stream_callback(fallback_msg, [], "partial_ai")
        except Exception:
            pass
    return {"messages": [AIMessage(content=fallback_msg)], "vec_results": [], "waiting": -1}


def assign_workers_by_plan(state: Dict[str, Any]):
    """Conditional callback: 根据当前 stage 产生 Send 列表（不写 state）。"""
    plan = state.get("plan") or {}
    stages = plan.get("stages") or []
    stage_index = int(state.get("stage_index") or 0)
    if stage_index >= len(stages):
        return []
    stage = stages[stage_index] or {}
    raw_steps = stage.get("steps") or []
    steps = [s for s in raw_steps if (s.get("when", True) is not False)]
    if not steps:
        return []
    parallel = bool(stage.get("parallel"))
    sends: List[Send] = []
    for step in (steps if parallel else [steps[0]]):
        call = (step.get("call") or "").lower()
        args = step.get("args") or {}
        if call == "sql":
            # 仅传递该子图所需入参与可增量合并的 messages；
            # 避免在并行分支写顶层的 thread_id/user_id 以消除并发冲突
            sql_state = {"sql_in": args, "waiting": 0}
            sql_state.update({
                "messages": state.get("messages", []),
            })
            sends.append(Send("SQL_Subgraph", sql_state))
            print(f"[Orchestrator] Sending to SQL_Subgraph: sql_in={args} user_id={state.get('user_id')}")
        elif call == "vec":
            # 仅传递该子图所需入参与可增量合并的 messages；
            # 避免在并行分支写顶层的 thread_id/user_id 以消除并发冲突
            vec_state = {"vec_in": args, "waiting": 0}
            vec_state.update({
                "messages": state.get("messages", []),
            })
            sends.append(Send("Vector_Subgraph", vec_state))
            print(f"[Orchestrator] Sending to Vector_Subgraph: vec_in={args} user_id={state.get('user_id')}")
        elif call == "kg":
            # 仅传递该子图所需入参与可增量合并的 messages；
            # 避免在并行分支写顶层的 thread_id/user_id 以消除并发冲突
            kg_state = {"kg_in": args, "waiting": 0}
            kg_state.update({
                "messages": state.get("messages", []),
            })
            sends.append(Send("KG_Subgraph", kg_state))
            print(f"[Orchestrator] Sending to KG_Subgraph: kg_in={args} user_id={state.get('user_id')}")
    try:
        print(f"[Orchestrator] stage_index={stage_index} steps={len(steps)} parallel={parallel} sends={len(sends)}")
        if getattr(settings, 'trace_events', False):
            try:
                preview = []
                for s in (steps if parallel else [steps[0]]):
                    if isinstance(s, dict):
                        preview.append({"call": s.get("call"), "argsKeys": list((s.get("args") or {}).keys())[:5]})
                call_stream_callback(state.get('thread_id'), {"stageIndex": stage_index, "parallel": parallel, "steps": preview}, [], "dispatch")
            except Exception:
                pass
    except Exception:
        pass
    return sends


async def orchestrator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Orchestrator 占位节点：不写入、不返回 Send，仅作为 conditional 起点。"""
    return {}


def set_barrier(state: Dict[str, Any]) -> Dict[str, Any]:
    """根据当前 stage 设置 barrier(waiting)。顺序=1，并行=并发任务数。"""
    plan = state.get("plan") or {}
    stages = plan.get("stages") or []
    stage_index = int(state.get("stage_index") or 0)
    if stage_index >= len(stages):
        return {"waiting": 0}
    stage = stages[stage_index] or {}
    raw_steps = stage.get("steps") or []
    steps = [s for s in raw_steps if (s.get("when", True) is not False)]
    if not steps:
        return {"waiting": 0}
    parallel = bool(stage.get("parallel"))
    waiting = len(steps) if parallel else 1
    
    # ⚠️ 关键问题：operator.add 无法清空旧数据
    # 
    # 根据官方文档 Persistence.txt 第186行：
    # - 有 reducer 的字段：累加（old + new）
    # - 无 reducer 的字段：覆盖（new 替换 old）
    #
    # 使用 operator.add 时：[] + [旧数据] = [旧数据]（无法清空！）
    #
    # 官方解决方案（根据 parallel_solution.txt 第83-84行）：
    # "运行过程中不要再用 sql_results=[] 之类的清空写入；
    #  要初始化清空，放到启动新对话/新 run 的初始状态里"
    #
    # 因此这里不尝试清空（会在 collect_base_data 的初始化中处理）
    result = {"waiting": waiting}
    
    # 检测旧数据并警告（但不清空，让 operator.add 自然累加）
    if stage_index == 0:
        old_sql = state.get("sql_results", [])
        old_vec = state.get("vec_results", [])
        old_kg = state.get("kg_results", [])
        old_merged = state.get("merged", [])
        if old_sql or old_vec or old_kg or old_merged:
            print(f"[Barrier] WARNING: Detected stale data - sql:{len(old_sql) if isinstance(old_sql, list) else 0}, vec:{len(old_vec) if isinstance(old_vec, list) else 0}, kg:{len(old_kg) if isinstance(old_kg, list) else 0}, merged:{len(old_merged) if isinstance(old_merged, list) else 0}")
            print(f"[Barrier] Note: With operator.add reducer, stale data will accumulate. Need to clear at invocation level.")
    
    try:
        print(f"[Barrier] stage_index={stage_index} steps={len(steps)} parallel={parallel} waiting={waiting}")
    except Exception:
        pass
    return result


async def SQL_Subgraph(state: Dict[str, Any]) -> Dict[str, Any]:
    """SQL 子图：从 sql_in 解析参数并调用 MySQL 工具，支持完整观测。"""
    try:
        # 参数解析和调试
        params = state.get("sql_in") or {}
        user_id = state.get("user_id")
        thread_id = state.get("thread_id")
        
        print(f"[SQL][Prepare] State keys: {list(state.keys())}")
        print(f"[SQL][Prepare] sql_in: {params}")
        
        # 智能工具选择逻辑：根据参数格式选择合适的工具
        print(f"[SQL] Looking for MySQL tools in TOOL_BY_NAME...")
        
        tool = None
        final_params = {}
        
        if not isinstance(params, dict):
            print(f"[SQL] ERROR: sql_in must be a dict, got {type(params)}")
            return {"sql_results": [], "waiting": -1}
        
        # 检查参数格式，选择合适的工具
        if "table" in params and "fields" in params:
            # 标准 simple query 格式
            tool = TOOL_BY_NAME.get("mysql_simple_query_tool")
            final_params = params
            print(f"[SQL] Using mysql_simple_query_tool (detected table+fields)")
        elif "query_draft" in params:
            # Custom query 格式 - query_draft 应该是一个 dict
            if isinstance(params.get("query_draft"), dict):
                tool = TOOL_BY_NAME.get("mysql_custom_query_tool")
                final_params = params
                print(f"[SQL] Using mysql_custom_query_tool (query_draft is dict)")
            else:
                # query_draft 是 string，无法直接使用，返回错误
                print(f"[SQL] ERROR: query_draft must be a dict, got {type(params.get('query_draft'))}")
                print(f"[SQL] Hint: Use simple query format with table+fields instead")
                return {"sql_results": [], "waiting": -1}
        else:
            # 尝试使用 simple query 工具，假设参数包含必要字段
            tool = TOOL_BY_NAME.get("mysql_simple_query_tool")
            # 设置默认值
            final_params = {
                "table": params.get("table", "order"),
                "fields": params.get("fields", ["*"]),
                "conditions": params.get("conditions", {}),
                "limit": params.get("limit", 10),
                "offset": params.get("offset", 0),
            }
            if "order_by" in params:
                final_params["order_by"] = params["order_by"]
            print(f"[SQL] Using mysql_simple_query_tool (default)")
        
        if not tool:
            print(f"[SQL] ERROR: MySQL tool not found in TOOL_BY_NAME!")
            print(f"[SQL] Available tools: {list(TOOL_BY_NAME.keys())}")
            return {"sql_results": [], "waiting": -1}
        
        # 注入user_id如果工具支持
        if user_id and isinstance(final_params, dict) and "user_id" not in final_params:
            final_params["user_id"] = user_id
            
        # 数据检索过程对用户透明，不发送前端通知
        print(f"[SQL] About to call {tool.name} with params: {final_params}")
        
        # 工具调用
        res = await tool.ainvoke(final_params)
        data = res.get("data") if isinstance(res, dict) else []
        if not isinstance(data, list):
            data = []
            
        print(f"[SQL] Tool returned {len(data)} records")
        
        # 打印前3条数据用于调试
        if data:
            print(f"[SQL] First record sample: {data[0] if len(data) > 0 else 'N/A'}")
            print(f"[SQL] Total records to return: {len(data)}")
        else:
            print(f"[SQL] WARNING: No data returned from tool!")
        
        # 数据通过 state.sql_results 传递，无需前端通知
        result = {"sql_results": data, "waiting": -1}
        print(f"[SQL] Returning to parent: sql_results with {len(data)} items, waiting=-1")
            
        return result
    except Exception as e:
        print(f"[SQL_Subgraph] error: {e}")
        import traceback
        print(f"[SQL_Subgraph] traceback: {traceback.format_exc()}")
        return {"sql_results": []}


async def KG_Subgraph(state: Dict[str, Any]) -> Dict[str, Any]:
    """KG 子图：路由到 graphiti_* 工具，统一输出 kg_results。"""
    try:
        # 参数解析和调试
        params = state.get("kg_in") or {}
        
        print(f"[KG][Prepare] State keys: {list(state.keys())}")
        print(f"[KG][Prepare] kg_in: {params}")
        if not isinstance(params, dict):
            return {"kg_results": [], "waiting": -1}
        call_type = (params.get("type") or "").lower()
        args = params.get("args") or {}
        try:
            print(f"[KG] call_type={call_type} args_keys={(list(args.keys())[:5] if isinstance(args, dict) else [])}")
        except Exception:
            pass
        # Ensure user context pass-through if available
        user_id = state.get("user_id") or args.get("user_id")
        if user_id and isinstance(args, dict) and "user_id" not in args:
            args["user_id"] = user_id
        thread_id = state.get("thread_id")
        # 数据检索过程对用户透明，不发送前端通知

        # 工具查找和路由
        print(f"[KG] Looking for graphiti tools in TOOL_BY_NAME...")
        
        if call_type == "graph.search":
            tool = TOOL_BY_NAME.get("graphiti_search_tool")
            print(f"[KG] Tool 'graphiti_search_tool' found: {tool is not None}")
            if not tool:
                print(f"[KG] ERROR: graphiti_search_tool not found in TOOL_BY_NAME!")
                print(f"[KG] Available tools: {[t for t in TOOL_BY_NAME.keys() if 'graphiti' in t]}")
                return {"kg_results": [], "waiting": -1}
            
            print(f"[KG] About to call graphiti_search_tool with args: {args}")
            res = await tool.ainvoke(args)
            data = res.get("data") if isinstance(res, dict) else []
            try:
                total = len(data) if isinstance(data, list) else 0
                print(f"[KG] graph.search returned {total} items")
                # 数据通过 state.kg_results 传递，无需前端通知
            except Exception:
                pass
            return {"kg_results": data if isinstance(data, list) else [], "waiting": -1}

        if call_type == "graph.write.episode":
            tool = TOOL_BY_NAME.get("graphiti_add_episode_tool")
            print(f"[KG] Tool 'graphiti_add_episode_tool' found: {tool is not None}")
            if not tool:
                print(f"[KG] ERROR: graphiti_add_episode_tool not found!")
                return {"kg_results": [], "waiting": -1}
            
            print(f"[KG] About to call graphiti_add_episode_tool with args: {args}")
            res = await tool.ainvoke(args)
            ok = bool(res.get("success")) if isinstance(res, dict) else False
            item = {"text": "episode_written" if ok else "episode_failed", "metadata": res}
            return {"kg_results": [item], "waiting": -1}

        if call_type == "graph.write.entity":
            tool = TOOL_BY_NAME.get("graphiti_add_entity_tool")
            print(f"[KG] Tool 'graphiti_add_entity_tool' found: {tool is not None}")
            if not tool:
                print(f"[KG] ERROR: graphiti_add_entity_tool not found!")
                return {"kg_results": [], "waiting": -1}
            
            print(f"[KG] About to call graphiti_add_entity_tool with args: {args}")
            res = await tool.ainvoke(args)
            ok = bool(res.get("success")) if isinstance(res, dict) else False
            item = {"text": "entity_written" if ok else "entity_failed", "metadata": res}
            return {"kg_results": [item], "waiting": -1}

        if call_type == "graph.write.edge":
            tool = TOOL_BY_NAME.get("graphiti_add_edge_tool")
            print(f"[KG] Tool 'graphiti_add_edge_tool' found: {tool is not None}")
            if not tool:
                print(f"[KG] ERROR: graphiti_add_edge_tool not found!")
                return {"kg_results": [], "waiting": -1}
            
            print(f"[KG] About to call graphiti_add_edge_tool with args: {args}")
            res = await tool.ainvoke(args)
            ok = bool(res.get("success")) if isinstance(res, dict) else False
            item = {"text": "edge_written" if ok else "edge_failed", "metadata": res}
            return {"kg_results": [item], "waiting": -1}

        if call_type == "graph.ingest.detect":
            tool = TOOL_BY_NAME.get("graphiti_ingest_detect_tool")
            print(f"[KG] Tool 'graphiti_ingest_detect_tool' found: {tool is not None}")
            if not tool:
                print(f"[KG] ERROR: graphiti_ingest_detect_tool not found!")
                return {"kg_results": [], "waiting": -1}
            
            print(f"[KG] About to call graphiti_ingest_detect_tool with args: {args}")
            res = await tool.ainvoke(args)
            item = {"text": "ingest_detect", "metadata": res}
            return {"kg_results": [item], "waiting": -1}

        if call_type == "graph.ingest.commit":
            tool = TOOL_BY_NAME.get("graphiti_ingest_commit_tool")
            print(f"[KG] Tool 'graphiti_ingest_commit_tool' found: {tool is not None}")
            if not tool:
                print(f"[KG] ERROR: graphiti_ingest_commit_tool not found!")
                return {"kg_results": [], "waiting": -1}
            
            print(f"[KG] About to call graphiti_ingest_commit_tool with args: {args}")
            res = await tool.ainvoke(args)
            item = {"text": "ingest_commit", "metadata": res}
            return {"kg_results": [item], "waiting": -1}

        # default
        return {"kg_results": [], "waiting": -1}
    except Exception as e:
        print(f"[KG_Subgraph] error: {e}")
        return {"kg_results": []}


async def aggregate_normalize_optional(state: Dict[str, Any]) -> Dict[str, Any]:
    """聚合器：合并所有数据源的结果
    
    ✅ 官方 Fan-in 模式（自动等待所有并行节点完成）
    根据以下官方文档：
    - graph.txt 第61行："channel updates remain invisible... until the next step"
    - parallel_solution.txt 第135行："你不用在节点里写'等所有子任务完成'的检查"
    
    LangGraph 的 Superstep 机制保证：
    1. SQL_Subgraph 和 Vector_Subgraph 在 Super-step N 并行执行
    2. 它们的状态更新在 Super-step N 的 Update Phase 通过 reducer 合并
    3. 本节点在 Super-step N+1 执行，自动看到所有并行节点的合并结果
    
    因此无需手动检查 waiting 或使用自循环，LangGraph 会自动等待。
    """
    # 读取所有数据源（此时所有并行任务已完成，数据已通过 operator.add 合并）
    sql_results = state.get("sql_results") or []
    vec_results = state.get("vec_results") or []
    kg_results = state.get("kg_results") or []
    
    print(f"[Agg] Entry: 自动 fan-in 完成，开始合并数据")
    
    print(f"[Agg] Data sources:")
    print(f"[Agg]   sql_results: {len(sql_results) if isinstance(sql_results, list) else 'not-list'} items")
    print(f"[Agg]   vec_results: {len(vec_results) if isinstance(vec_results, list) else 'not-list'} items")
    print(f"[Agg]   kg_results: {len(kg_results) if isinstance(kg_results, list) else 'not-list'} items")
    
    if sql_results:
        print(f"[Agg]   sql_results[0] sample: {sql_results[0] if len(sql_results) > 0 else 'N/A'}")
    
    merged: List[Dict[str, Any]] = []
    for key in ("sql_results", "vec_results", "kg_results"):
        vals = state.get(key) or []
        if isinstance(vals, list):
            merged.extend(vals)
            print(f"[Agg]   Added {len(vals)} items from {key} to merged")
    
    print(f"[Agg] Total merged items: {len(merged)}")
    
    # 简单 fast-path：如果仅有 sql 或 kg 且 merged 非空，标记 deterministic
    deterministic = False
    present = [k for k in ("sql_results", "kg_results", "vec_results") if state.get(k)]
    if present and all(k in ("sql_results", "kg_results") for k in present) and merged:
        deterministic = True
    # 推进 stage
    stage_index = int(state.get("stage_index") or 0)
    plan = state.get("plan") or {}
    total = len(plan.get("stages") or [])
    more = stage_index + 1 < total
    route = "more" if more else ("fast" if deterministic else "done")
    try:
        print(f"[Agg] present={present} merged={len(merged)} route={route} stage_index={stage_index}/{max(total-1,0)} deterministic={deterministic}")
        if getattr(settings, 'trace_events', False):
            call_stream_callback(state.get('thread_id'), {"present": present, "merged": len(merged), "route": route, "stageIndex": stage_index}, [], "aggregate")
    except Exception:
        pass
    nxt = {"merged": merged, "agg_route": route}
    if more:
        nxt["stage_index"] = stage_index + 1
    
    print(f"[Agg] Returning: merged={len(merged)} items, agg_route={route}")
    return nxt


async def response_writer(state: Dict[str, Any]) -> Dict[str, Any]:
    """统一写出：基于 merged 或单一路径结果生成回答。"""
    stream_callback = state.get("stream_callback")
    messages = state.get("messages", [])
    
    # 获取并合并数据源
    merged_data = state.get("merged", [])
    vec_data = state.get("vec_results", [])
    sql_data = state.get("sql_results", [])
    kg_data = state.get("kg_results", [])
    
    print(f"[Writer] Entry: Received data sources:")
    print(f"[Writer]   merged_data: {len(merged_data) if isinstance(merged_data, list) else 'not-list'} items")
    print(f"[Writer]   vec_data: {len(vec_data) if isinstance(vec_data, list) else 'not-list'} items")
    print(f"[Writer]   sql_data: {len(sql_data) if isinstance(sql_data, list) else 'not-list'} items")
    print(f"[Writer]   kg_data: {len(kg_data) if isinstance(kg_data, list) else 'not-list'} items")
    
    if sql_data:
        print(f"[Writer]   sql_data[0] sample: {sql_data[0] if len(sql_data) > 0 else 'N/A'}")
    if merged_data:
        print(f"[Writer]   merged_data[0] sample: {merged_data[0] if len(merged_data) > 0 else 'N/A'}")
    
    merged = merged_data or vec_data or sql_data or kg_data
    print(f"[Writer] Final merged to use: {len(merged) if isinstance(merged, list) else 'not-list'} items")
    
    # 构建预览内容（支持向量搜索和SQL数据两种格式）
    preview_lines = []
    preview_errors = []
    data_type = "unknown"
    # ✅ 添加混合数据检测
    has_sql_data = False
    has_vector_data = False
    
    # 根据数据源类型决定显示数量
    # SQL查询：显示全部（因为已经通过limit控制）
    # 向量搜索：限制前20条（避免提示词过长）
    display_limit = len(merged) if len(merged) <= 20 else 20
    
    try:
        for i, item in enumerate(merged[:display_limit], start=1):
            # ✅ 调试：打印每个item的前100个字符
            print(f"[Writer] Processing item {i}/{display_limit}: keys={list(item.keys())[:5] if isinstance(item, dict) else 'not-dict'}")
            if isinstance(item, dict):
                # 向量搜索数据：有 text 字段
                text = item.get("text", "")
                if text:
                    has_vector_data = True
                    print(f"[Writer]   → Vector data (text field): {text[:50]}...")
                    preview_lines.append(f"[{i}] {text}")
                    continue
                
                # 尝试其他文本字段
                text = item.get("content", "") or item.get("snippet", "") or item.get("description", "")
                if text.strip():
                    has_vector_data = True
                    print(f"[Writer]   → Vector data (other text field): {text[:50]}...")
                    preview_lines.append(f"[{i}] {text}")
                    continue
                
                # SQL数据：结构化dict（如订单记录），转换为可读格式
                if any(k in item for k in ["order_id", "uid", "province", "pay_price", "create_time"]):
                    has_sql_data = True
                    print(f"[Writer]   → SQL data (order_id={item.get('order_id', 'N/A')})")
                    # 格式化订单数据
                    fields = []
                    if "order_id" in item:
                        fields.append(f"订单号:{item['order_id']}")
                    if "order_sn" in item:
                        fields.append(f"订单编号:{item['order_sn']}")
                    if "province" in item and "city" in item:
                        fields.append(f"地区:{item['province']}{item['city']}")
                    if "pay_price" in item:
                        fields.append(f"金额:{item['pay_price']}元")
                    if "pay_time" in item:
                        fields.append(f"支付时间:{item['pay_time']}")
                    if "create_time" in item:
                        fields.append(f"创建时间:{item['create_time']}")
                    if "status" in item:
                        status_map = {0: "待付款", 1: "已付款", 2: "已发货", 3: "已完成", 4: "已退款"}
                        fields.append(f"状态:{status_map.get(item['status'], item['status'])}")
                    
                    preview_lines.append(f"[{i}] " + "，".join(fields))
                    continue
                
                # 其他结构化数据，转为JSON字符串
                preview_errors.append(f"第{i}个item格式未知: {str(item)[:100]}")
            else:
                text = str(item)
                preview_lines.append(f"[{i}] {text}")
    except Exception as e:
        preview_errors.append(f"处理异常: {e}")
    
    # ✅ 根据数据来源智能设置 data_type
    if has_sql_data and has_vector_data:
        data_type = "mixed"
    elif has_sql_data:
        data_type = "sql"
    elif has_vector_data:
        data_type = "vector"
    
    print(f"[Writer] Preview: data_type={data_type} (sql={has_sql_data}, vec={has_vector_data}), preview_lines={len(preview_lines)}, errors={len(preview_errors)}, total={len(merged)}")
    if preview_errors:
        print(f"[Writer] Preview errors: {preview_errors[:3]}")
    
    # 构建系统消息（根据数据类型调整提示）
    truncated = len(merged) > len(preview_lines)
    
    # ✅ 调试：打印 preview_lines 的前3行
    print(f"[Writer] Preview lines (first 3):")
    for idx, line in enumerate(preview_lines[:3], 1):
        print(f"[Writer]   Line {idx}: {line[:100]}...")
    
    if preview_lines:
        if data_type == "sql":
            header = f"你是严谨的数据分析助手。数据库查询已完成，共返回{len(merged)}条记录"
            if truncated:
                header += f"（以下展示前{len(preview_lines)}条）"
            header += "。\n\n⚠️ 重要：以下数据就是你作答所需的证据。必须严格基于这些数据回答，不得输出诸如\"未找到\"、\"证据不足\"、\"无法访问数据库\"等措辞。\n\n"
            sys_content = header + "\n".join(preview_lines) + "\n\n请用自然语言总结这些数据并直接回答用户的问题。"
        elif data_type == "mixed":
            # Vector + SQL 混合：明确强制使用证据
            header = f"你是严谨的助手。数据库查询和文档搜索已完成，共返回{len(merged)}条数据"
            if truncated:
                header += f"（以下展示前{len(preview_lines)}条）"
            header += "。\n\n⚠️ 重要：以下数据就是你作答所需的证据。必须严格基于这些数据回答，不得输出\"未找到\"、\"证据不足\"、\"请自己查询\"等措辞。\n\n"
            sys_content = header + "\n".join(preview_lines) + "\n\n请用自然语言总结这些数据并回答用户问题；如引用文档内容，请使用编号如[1][2]。"
        else:
            # Vector 类型：强制使用证据
            header = f"你是一个专业的信息分析助手。你的任务是基于下列证据总结并回答用户问题。\n\n"
            header += f"📊 任务背景：检索到{len(merged)}个相关文档"
            if truncated:
                header += f"（以下展示前{len(preview_lines)}个）"
            header += "。\n\n"
            header += f"📋 作答要求：\n"
            header += f"1. 仅基于下方编号为[1]到[{len(preview_lines)}]的文档内容作答；\n"
            header += f"2. 必要时引用编号（如：根据[1][2]）；\n"
            header += f"3. 严禁输出\"未找到\"、\"证据不足\"等措辞（因为已提供证据）；\n\n"
            header += f"📄 文档内容：\n"
            sys_content = header + "\n".join(preview_lines)
    else:
        sys_content = "你是严谨的助手。搜索已完成，但没有找到相关内容。请告知用户搜索未找到匹配的结果。"
    
    sys = SystemMessage(content=sys_content)
    
    # ✅ 调试：打印完整 system prompt（用于诊断）
    print(f"[Writer] System prompt (first 200 chars): {sys_content[:200]}...")
    print(f"[Writer] System prompt length: {len(sys_content)} characters")
    # 打印完整prompt到文件，避免终端截断
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_writer_prompt.txt', prefix='debug_') as f:
            f.write(sys_content)
            print(f"[Writer] Full system prompt saved to: {f.name}")
    except Exception as e:
        print(f"[Writer] Failed to save prompt to file: {e}")
    # 同时打印最后200个字符，看看结尾
    print(f"[Writer] System prompt (last 200 chars): ...{sys_content[-200:]}")
    
    full_content = ""
    try:
        print("[Writer] start streaming")
        if getattr(settings, 'trace_events', False):
            call_stream_callback(state.get('thread_id'), {"event": "writer_start"}, [], "writer_start")
    except Exception:
        pass
    try:
        async for chunk in llm.astream([sys] + messages):
            content = getattr(chunk, 'content', '') or ''
            if not content:
                continue
            full_content += content
            # 优先使用线程级回调进行 SSE 推流，回退到节点本地回调
            try:
                call_stream_callback(state.get('thread_id'), content, [], "partial_ai")
            except Exception:
                if stream_callback:
                    try:
                        stream_callback(content, [], "partial_ai")
                    except Exception:
                        pass
        try:
            print(f"[Writer] done, length={len(full_content)}")
            if getattr(settings, 'trace_events', False):
                call_stream_callback(state.get('thread_id'), {"event": "writer_done", "length": len(full_content)}, [], "writer_done")
        except Exception:
            pass
        return {"final_answer": full_content, "messages": [AIMessage(content=full_content)]}
    except Exception as e:
        print(f"[Writer] error: {e}")
        return {"final_answer": "", "messages": [AIMessage(content="抱歉，生成回答时发生错误。")]}


async def simple_response(state: dict) -> Dict[str, Any]:
    """Generate simple response (tool or no-tool)."""
    intent = state.get('intent')
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    
    print("[SimpleResponse] 生成简单回复")
    try:
        thread_id = state.get('thread_id')
        roles_summary = []
        try:
            for m in messages:
                try:
                    if isinstance(m, AIMessage):
                        roles_summary.append("ai")
                    elif isinstance(m, HumanMessage):
                        roles_summary.append("human")
                    elif isinstance(m, SystemMessage):
                        roles_summary.append("system")
                    else:
                        roles_summary.append(type(m).__name__)
                except Exception:
                    roles_summary.append("unknown")
        except Exception:
            pass
        print(f"[SimpleResponse] msgs={len(messages)} roles={roles_summary} thread_id={thread_id} cb={'yes' if stream_callback else 'no'}")
    except Exception:
        pass
    
    try:
        # Use conversation messages (and optional tool results) to answer directly
        full_content = ""
        chunk_count = 0
        async for chunk in llm.astream(messages):
            content = getattr(chunk, 'content', '') or ''
            if not content:
                continue
            chunk_count += 1
            # 简化chunk日志：只显示前3条和每50条一次，以及最后一条
            if settings.debug and (chunk_count <= 3 or (chunk_count % 50 == 0)):
                try:
                    log_with_limit("[SimpleResponse] 收到chunk ", content, 100)
                except Exception:
                    pass
            # 使用线程级回调，确保经由 server.py 的 SSE 推送到前端
            try:
                call_stream_callback(state.get('thread_id'), content, [], "partial_ai")
            except Exception:
                pass
            full_content += content
        result_message = AIMessage(content=full_content)
        try:
            total_len = len(full_content)
            print(f"[SimpleResponse] 完成流式生成，chunks={chunk_count} total_len={total_len}")
            # 友好的头尾预览：避免末尾 '...' 让人误解为模型输出
            if total_len <= 300:
                print(f"[SimpleResponse] 输出全文: {full_content}")
            else:
                head = full_content[:150]
                tail = full_content[-150:]
                omitted = total_len - 300
                print(f"[SimpleResponse] 输出预览: {head} [omitted {omitted} chars] {tail}")
        except Exception:
            pass
        return {"messages": [result_message], "intent": intent, "stream_callback": stream_callback}
        
    except Exception as e:
        print(f"[SimpleResponse] 生成回复失败: {e}")
        error_message = AIMessage(content=f"抱歉，生成回复时出现错误: {str(e)}")
        return {"messages": [error_message], "intent": intent, "stream_callback": stream_callback}


def create_graph() -> StateGraph:
    """Create the LangGraph workflow"""
    
    # Create the graph with dict state
    workflow = StateGraph(AppState)
    
    # Add nodes
    workflow.add_node("intent_slot_detect", intent_slot_detect)
    workflow.add_node("detect_intent", detect_intent)
    workflow.add_node("collect_base_data", collect_base_data)
    # simple response node
    workflow.add_node("simple_response", simple_response)
    # planner / orchestrator path
    workflow.add_node("planner", plan_node)
    # barrier setter for orchestrator
    workflow.add_node("set_barrier", set_barrier)
    # Orchestrator 节点本身不派发，仅作为 conditional 起点
    workflow.add_node("Orchestrator", orchestrator_node)
    workflow.add_node("aggregate_normalize_optional", aggregate_normalize_optional)
    workflow.add_node("response_writer", response_writer)
    # subgraphs as nodes
    workflow.add_node("SQL_Subgraph", SQL_Subgraph)
    workflow.add_node("KG_Subgraph", KG_Subgraph)
    # Build Vector subgraph (shared state schema) replacing RAG
    vector_builder = StateGraph(AppState)
    vector_builder.add_node("vector_prepare", vector_prepare)
    vector_builder.add_node("vector_fetch_evidence", vector_fetch_evidence)
    vector_builder.add_node("vector_assess", vector_assess)
    vector_builder.add_node("vector_rewrite", vector_rewrite)
    vector_builder.add_node("vector_answer", vector_answer)
    vector_builder.add_node("vector_fallback", vector_fallback)
    vector_builder.add_edge("vector_prepare", "vector_fetch_evidence")
    vector_builder.add_edge("vector_fetch_evidence", "vector_assess")
    def _route_after_vector_assess(state: dict) -> str:
        dec = state.get("vector_decision")
        if dec == "rewrite":
            return "vector_rewrite"
        if dec == "fallback":
            return "vector_fallback"
        return "vector_answer"

    vector_builder.add_conditional_edges(
        "vector_assess",
        _route_after_vector_assess,
        {"vector_rewrite": "vector_rewrite", "vector_fallback": "vector_fallback", "vector_answer": "vector_answer"},
    )
    vector_builder.add_edge("vector_rewrite", "vector_fetch_evidence")
    # 统一为工作站风格：返回 vec_results 由父级聚合
    # 在 answer/fallback 节点内输出 vec_results 并结束子图
    vector_builder.add_edge("vector_answer", END)
    vector_builder.add_edge("vector_fallback", END)
    vector_builder.set_entry_point("vector_prepare")
    Vector_Subgraph = vector_builder.compile()
    workflow.add_node("Vector_Subgraph", Vector_Subgraph)
    
    # Add edges
    workflow.add_edge("intent_slot_detect", "detect_intent")
    workflow.add_edge("detect_intent", "collect_base_data")
    
    # Conditional routing after base data collection to tools/simple
    def _route_after_collect(state: dict) -> str:
        try:
            # 若已经流式输出过（regular分支），则直接结束
            if state.get("already_streamed"):
                print("[Route] after collect: already_streamed=True → END")
                return "END"
            # 非工具意图：走简单回复
            if state.get("intent") != "tool":
                print("[Route] after collect: intent!=tool → simple")
                return "simple"
            # 工具意图：基于 collect 探测结果判断是否进入 plan
            has_calls = bool(state.get("candidate_tool_calls"))
            dest = "tools" if has_calls else "simple"
            print(f"[Route] after collect: intent=tool has_calls={has_calls} → {dest}")
            return dest
        except Exception:
            print("[Route] after collect: exception → simple")
            return "simple"

    workflow.add_conditional_edges(
        "collect_base_data",
        _route_after_collect,
        {"tools": "planner", "simple": "simple_response", "END": END},
    )

    # Orchestrator fan-out and aggregation（Send only via conditional edges）
    # planner -> set_barrier -> Orchestrator
    workflow.add_edge("planner", "set_barrier")
    workflow.add_edge("set_barrier", "Orchestrator")
    # Orchestrator conditional edges: dynamic fan-out to workers
    workflow.add_conditional_edges(
        "Orchestrator",
        assign_workers_by_plan,
        {"SQL_Subgraph": "SQL_Subgraph", "Vector_Subgraph": "Vector_Subgraph", "KG_Subgraph": "KG_Subgraph"},
    )
    # aggregator由各子图触发
    # ⚠️ 关键修复：使用普通边，LangGraph会自动等待所有输入完成（Fan-in模式）
    workflow.add_edge("SQL_Subgraph", "aggregate_normalize_optional")
    workflow.add_edge("Vector_Subgraph", "aggregate_normalize_optional")
    workflow.add_edge("KG_Subgraph", "aggregate_normalize_optional")
    
    # Aggregator 到下一步的路由
    def _route_from_agg(state: dict) -> str:
        agg_route = state.get("agg_route", "done")
        print(f"[Route] agg_route={agg_route}, routing to target")
        return agg_route
    
    workflow.add_conditional_edges(
        "aggregate_normalize_optional",
        _route_from_agg,
        {
            "more": "Orchestrator",
            "fast": "response_writer",
            "done": "response_writer"
        },
    )

    # simple response branch
    workflow.add_edge("simple_response", END)
    
    # Set entry point
    workflow.set_entry_point("intent_slot_detect")
    
    return workflow


"""
Create the graph instance with checkpointer (PG preferred, fallback to in-memory).
At import time we prefer a lazy, auto-reconnecting saver to avoid holding a dead
connection during long idle periods before the first request.
"""
try:
    from .auto_reconnect_checkpointer import AutoReconnectCheckpointer
    from .checkpointer_adapter import MinimalCheckpointerAdapter  # 恢复使用，但已修复反序列化
    _pg_dsn = getattr(settings, "pg_dsn", None)
    if _pg_dsn:
        _auto = AutoReconnectCheckpointer(_pg_dsn, max_retry=1, setup_on_connect=True)
        _checkpointer = MinimalCheckpointerAdapter(_auto)  # 使用修复后的 adapter
        try:
            print("[Graph] Using AutoReconnectCheckpointer with MinimalCheckpointerAdapter (fixed deserialization)")
        except Exception:
            pass
    else:
        raise ImportError("PG_DSN not configured")
except Exception as _e:
    try:
        from langgraph.checkpoint.memory import InMemorySaver
        _checkpointer = InMemorySaver()
        print(f"[Graph] Using InMemorySaver checkpointer due to: {_e}")
    except Exception:
        _checkpointer = None  # last resort

if _checkpointer is not None:
    graph = create_graph().compile(checkpointer=_checkpointer)
else:
    graph = create_graph().compile()

try:
    used = type(_checkpointer).__name__ if _checkpointer is not None else "None"
    print(f"[Graph] Checkpointer in use: {used}")
except Exception:
    pass


def export_graph_spec() -> Dict[str, Any]:
    """Export a static specification of the current graph for visualization tools.
    This does not introspect the compiled graph; instead, it mirrors the edges
    defined above to avoid relying on private APIs. Safe for external scripts.
    """
    nodes = [
        "intent_slot_detect",
        "detect_intent",
        "collect_base_data",
        "planner",
        "Orchestrator",
        "SQL_Subgraph",
        "Vector_Subgraph",
        "KG_Subgraph",
        "aggregate_normalize_optional",
        "response_writer",
        "simple_response",
        "END",
    ]

    edges = [
        {"from": "intent_slot_detect", "to": "detect_intent", "type": "edge"},
        {"from": "detect_intent", "to": "collect_base_data", "type": "edge"},

        # Conditional routing after collect_base_data
        {"from": "collect_base_data", "to": "planner", "type": "conditional", "label": "has tool_calls"},
        {"from": "collect_base_data", "to": "simple_response", "type": "conditional", "label": "no tool_calls"},

        # Planner/Orchestrator fan-out
        {"from": "planner", "to": "set_barrier", "type": "edge"},
        {"from": "set_barrier", "to": "Orchestrator", "type": "edge"},
        {"from": "SQL_Subgraph", "to": "aggregate_normalize_optional", "type": "edge"},
        {"from": "Vector_Subgraph", "to": "aggregate_normalize_optional", "type": "edge"},
        {"from": "KG_Subgraph", "to": "aggregate_normalize_optional", "type": "edge"},
        {"from": "aggregate_normalize_optional", "to": "response_writer", "type": "edge"},

        # Simple path
        {"from": "simple_response", "to": "END", "type": "edge"},

        
    ]

    return {"nodes": nodes, "edges": edges}