import asyncio
from typing import Dict, Any, List, Optional, Callable, Annotated, TypedDict
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
from ..core.config import settings
from ..core.system_prompt import system_message_content
from ..tools.registry import ALL_TOOLS_LIST
import uuid
import re


class AppState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], add_messages]
    intent: Optional[str]
    stream_callback: Optional[Callable]


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
            "stream_callback": self.stream_callback
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


# Initialize LLM
llm = ChatOpenAI(
    model="gpt-4-turbo",  
    openai_api_key=settings.openai_api_key,
    temperature=0.1,
    max_tokens=2048
)


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


async def detect_intent(state: dict) -> Dict[str, str]:
    """Detect user intent (regular conversation or tool usage)"""
    print("[DetectIntent] 开始检测意图")
    print(f"[DetectIntent] 状态类型: {type(state)}")
    print(f"[DetectIntent] 消息数量: {len(state.get('messages', []))}")
    print(f"[DetectIntent] 消息类型: {[type(msg) for msg in state.get('messages', [])]}")
    
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    print(f"[DetectIntent] stream_callback 类型: {type(stream_callback)}")
    print(f"[DetectIntent] stream_callback 值: {stream_callback}")
    
    user_input = get_last_user_message(messages)
    print(f"[DetectIntent] 获取到的用户输入: {user_input}")
    
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
    """Collect base data for regular conversation"""
    intent = state.get('intent')
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    
    print(f"[CollectBaseData] 开始收集基础数据，意图: {intent}")
    print(f"[CollectBaseData] stream_callback 类型: {type(stream_callback)}")
    print(f"[CollectBaseData] stream_callback 值: {stream_callback}")
    
    if intent == "regular":
        now = datetime.now()
        updated_system_message = SystemMessage(
            content=f"{system_message_content.content} 以当前时间 {now} 作为分析起点。"
        )
        
        # Prepare messages for streaming
        messages_for_llm = [updated_system_message] + messages
        
        print("[CollectBaseData] 开始流式生成常规对话回复")
        
        full_content = ""
        chunk_count = 0
        
        try:
            print(f"[CollectBaseData] 开始调用LLM，消息数量: {len(messages_for_llm)}")
            async for chunk in llm.astream(messages_for_llm):
                content = chunk.content if hasattr(chunk, 'content') else ""
                if not content:
                    continue
                
                chunk_count += 1
                full_content += content
                print(f"[CollectBaseData] 收到chunk {chunk_count}: {content[:50]}...")
                
                if stream_callback:
                    print(f"[CollectBaseData] 调用stream_callback: {stream_callback}")
                    
                    stream_callback(content, [], "partial_ai")
                else:
                    print(f"[CollectBaseData] stream_callback 是 None")
            
            print(f"[CollectBaseData] 流式生成完成，总 chunk 数: {chunk_count}, 完整内容: {full_content}")
            
            result_message = AIMessage(content=full_content)
            log_with_limit("常规对话回复: ", full_content, 300)
            
            return {"messages": [result_message], "intent": intent, "stream_callback": stream_callback}
            
        except Exception as e:
            print(f"[CollectBaseData] 流式生成失败: {e}")
            error_message = AIMessage(content=f"抱歉，生成回复时出现错误: {str(e)}")
            return {"messages": [error_message], "intent": intent, "stream_callback": stream_callback}
    
    # 工具调用逻辑
    now = datetime.now()
    updated_system_message = SystemMessage(
        content=f"{system_message_content.content} 当前时间是 {now.strftime('%Y-%m-%d %H:%M:%S')}，仅当用户需求涉及日期时使用此时间作为基准，并根据用户输入计算具体时间；若用户未提及日期，则不假设或填入任何时间。仅选择一个最相关工具调用，例如 date_calculator_tool（当用户问如‘上周三是什么时间’，可使用 base_date='today' 与 operations=[{{'type':'previous_weekday','value':'wednesday'}}]），或 mysql_simple_query_tool/hybrid_milvus_search_tool，用于查询用户指定的具体操作或信息。"
    )
    
    try:
        # 绑定工具到LLM
        llm_with_tools = llm.bind_tools(ALL_TOOLS_LIST)
        result = await llm_with_tools.ainvoke([updated_system_message] + messages)
        
        if hasattr(result, 'tool_calls') and result.tool_calls and len(result.tool_calls) > 0:
            # 添加流式传输：发送工具调用的AI消息
            if stream_callback:
                content = result.content if hasattr(result, 'content') else ""
                # 修改：正确调用stream_callback，传递partial_ai事件类型
                stream_callback(content, result.tool_calls, "partial_ai")
            
            updated_result = AIMessage(
                content=result.content or "",
                tool_calls=result.tool_calls
            )
            return {"messages": [updated_result], "intent": intent, "stream_callback": stream_callback}
        
        result_message = AIMessage(content=result.content)
        # 添加流式传输：发送AI消息
        if stream_callback:
            content = result.content if hasattr(result, 'content') else ""
            # 修改：正确调用stream_callback，传递partial_ai事件类型
            stream_callback(content, [], "partial_ai")
        
        log_with_limit("工具对话回复: ", result.content, 300)
        return {"messages": [result_message], "intent": intent, "stream_callback": stream_callback}
        
    except Exception as e:
        print(f"[CollectBaseData] 工具调用失败: {e}")
        error_message = AIMessage(content=f"抱歉，工具调用时出现错误: {str(e)}")
        return {"messages": [error_message], "intent": intent, "stream_callback": stream_callback}


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


async def execute_tools_in_parallel(state: dict) -> Dict[str, Any]:
    """Execute tools in parallel when intent is tool"""
    intent = state.get('intent')
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    
    if intent != "tool":
        return {"intent": intent, "stream_callback": stream_callback}
    
    # Get the last AI message to extract tool calls
    last_ai_message = None
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            last_ai_message = message
            break
    
    tool_calls = []
    if last_ai_message and hasattr(last_ai_message, 'tool_calls'):
        tool_calls = last_ai_message.tool_calls or []
    
    # Fallback: try heuristic date tool detection if no tool calls
    if not tool_calls:
        fallback = _detect_simple_date_tool_call(messages)
        if fallback:
            tool_calls = [fallback]
    
    if not tool_calls:
        print("[ExecuteTools] 没有工具调用，跳过执行")
        return {"intent": intent, "stream_callback": stream_callback}
    
    print(f"[ExecuteTools] 执行 {len(tool_calls)} 个工具调用")
    
    if stream_callback:
        # 修改：正确调用stream_callback，传递partial_ai事件类型
        stream_callback("工具执行中，请稍候...", [], "partial_ai")
    
    # 为工具调用生成ID（如果缺失）
    tool_calls_with_ids = []
    for tool_call in tool_calls:
        if not tool_call.get("id"):
            new_id = f"call_{uuid.uuid4().hex[:8]}"
            print(f"[ExecuteTools] 为工具调用 '{tool_call.get('name', '')}' 生成ID: {new_id}")
            tool_calls_with_ids.append({**tool_call, "id": new_id})
        else:
            tool_calls_with_ids.append(tool_call)
    
    # 并行执行工具
    TOOL_TIMEOUT = 30000  # 30秒超时
    
    async def execute_single_tool(tool_call):
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        
        # Find the tool function
        tool_func = None
        for tool in ALL_TOOLS_LIST:
            if tool.name == tool_name:
                tool_func = tool
                break
        
        if not tool_func:
            print(f"[ExecuteTools] 未找到工具: {tool_name}")
            return ToolMessage(
                content=f"未找到工具: {tool_name}",
                name=tool_name,
                tool_call_id=tool_call.get("id", "")
            )
        
        try:
            print(f"[ExecuteTools] 执行工具: {tool_name}")
            # 使用asyncio.wait_for实现超时
            result = await asyncio.wait_for(
                tool_func.ainvoke(tool_args),
                timeout=TOOL_TIMEOUT / 1000
            )
            
            safe_content = str(result) if result else "工具执行成功，但未返回内容。"
            print(f"[ExecuteTools] 工具 '{tool_name}' 执行成功，ID: {tool_call.get('id')}")
            
            return ToolMessage(
                content=safe_content,
                name=tool_name,
                tool_call_id=tool_call.get("id", "")
            )
            
        except asyncio.TimeoutError:
            print(f"[ExecuteTools] 工具 '{tool_name}' 执行超时")
            return ToolMessage(
                content=f"错误: 工具执行超时",
                name=tool_name,
                tool_call_id=tool_call.get("id", "")
            )
        except Exception as e:
            print(f"[ExecuteTools] 工具 '{tool_name}' 执行失败: {e}")
            return ToolMessage(
                content=f"错误: {str(e)}",
                name=tool_name,
                tool_call_id=tool_call.get("id", "")
            )
    
    # 并行执行所有工具
    tool_results = await asyncio.gather(*[execute_single_tool(tool_call) for tool_call in tool_calls_with_ids])
    
    if stream_callback:
        stream_callback("工具执行完成，正在生成回复...", [], "partial_ai")
        # 发送on_tool_end事件，通知前端工具执行完成
        stream_callback("", [], "on_tool_end")
    
    return {"messages": tool_results, "intent": intent, "stream_callback": stream_callback}


async def simple_response(state: dict) -> Dict[str, Any]:
    """Generate simple response after tool execution"""
    intent = state.get('intent')
    messages = state.get('messages', [])
    stream_callback = state.get('stream_callback')
    
    if intent != "tool":
        return {"intent": intent, "stream_callback": stream_callback}
    
    # Check if we have tool messages
    has_tool_messages = any(isinstance(msg, ToolMessage) for msg in messages)
    if not has_tool_messages:
        return {"intent": intent, "stream_callback": stream_callback}
    
    print("[SimpleResponse] 生成工具执行后的回复")
    
    try:
        # Generate response based on tool results
        async for chunk in llm.astream(messages):
            content = chunk.content if hasattr(chunk, 'content') else ""
            if not content:
                continue
            
            if stream_callback:
                
                stream_callback(content, [], "partial_ai")
        
        # Get the full response
        response = await llm.ainvoke(messages)
        result_message = AIMessage(content=response.content)
        
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
    workflow.add_node("detect_intent", detect_intent)
    workflow.add_node("collect_base_data", collect_base_data)
    workflow.add_node("execute_tools", execute_tools_in_parallel)
    workflow.add_node("simple_response", simple_response)
    
    # Add edges
    workflow.add_edge("detect_intent", "collect_base_data")
    workflow.add_edge("collect_base_data", "execute_tools")
    workflow.add_edge("execute_tools", "simple_response")
    workflow.add_edge("simple_response", END)
    
    # Set entry point
    workflow.set_entry_point("detect_intent")
    
    return workflow


# Create the graph instance
graph = create_graph().compile() 