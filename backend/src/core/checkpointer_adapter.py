"""
Checkpointer 适配器 - 解决 LangChain 消息序列化问题
基于最小化修改原则，仅处理 HumanMessage/AIMessage 等序列化问题
"""

from langchain_core.messages import BaseMessage, messages_to_dict, messages_from_dict
from typing import Any, Dict, List, Tuple, Iterable
from collections.abc import Mapping, Sequence, Set
import dataclasses
from datetime import datetime
from uuid import UUID
import json
import os
try:
    # Optional: used to explicitly detect Send objects
    from langgraph.types import Send as LGSend  # type: ignore
except Exception:  # pragma: no cover
    LGSend = None  # type: ignore


class MinimalCheckpointerAdapter:
    """
    最小化的 checkpointer 适配器，专门解决 HumanMessage 序列化问题
    
    特点：
    - 只处理 messages 字段的序列化/反序列化
    - 保持所有其他功能不变
    - 包含基础的错误处理和日志
    """
    
    def __init__(self, inner):
        self.inner = inner
        # 透传其他所有方法和属性
        for name in dir(inner):
            if not name.startswith('_') and name not in ('aput', 'aget', 'aget_tuple', 'alist'):
                try:
                    setattr(self, name, getattr(inner, name))
                except (AttributeError, TypeError):
                    pass  # 忽略不可设置的属性
    
    def __getattr__(self, name):
        """拦截所有未定义的方法调用"""
        return getattr(self.inner, name)
    
    def _serialize_messages_field(self, obj: Any) -> Any:
        """仅处理包含 messages 字段的情况"""
        if not isinstance(obj, dict):
            return obj
            
        result = {}
        for key, value in obj.items():
            if key == 'messages' and isinstance(value, list) and value:
                # 检查是否是 BaseMessage 列表
                if isinstance(value[0], BaseMessage):
                    try:
                        result[key] = {
                            '__type__': 'langchain_messages', 
                            '__version__': '1.0',
                            'data': messages_to_dict(value)
                        }
                    except Exception as e:
                        print(f"[CheckpointerAdapter] Message serialization failed: {e}")
                        result[key] = []  # fallback to empty list
                else:
                    result[key] = value
            else:
                result[key] = value
        return result
    
    def _deserialize_messages_field(self, obj: Any) -> Any:
        """仅处理包含序列化 messages 字段的情况"""
        if not isinstance(obj, dict):
            return obj
            
        result = {}
        for key, value in obj.items():
            if (key == 'messages' and isinstance(value, dict) and 
                value.get('__type__') == 'langchain_messages'):
                try:
                    messages = messages_from_dict(value['data'])
                    result[key] = messages
                except Exception as e:
                    print(f"[CheckpointerAdapter] Message deserialization failed: {e}")
                    result[key] = []  # fallback to empty list
            else:
                result[key] = value
        return result
    
    def _contains_send(self, obj: Any, max_depth: int = 3, current_depth: int = 0) -> bool:
        """递归检查对象中是否包含Send对象"""
        if current_depth > max_depth:
            return False
        try:
            # 检查是否是Send对象
            if obj.__class__.__name__ == "Send":
                return True
            if LGSend is not None and isinstance(obj, LGSend):
                return True
            # 递归检查容器
            if isinstance(obj, dict):
                return any(self._contains_send(v, max_depth, current_depth + 1) for v in obj.values())
            if isinstance(obj, (list, tuple, set)):
                return any(self._contains_send(item, max_depth, current_depth + 1) for item in obj)
        except Exception:
            pass
        return False

    # --- 通用递归序列化/反序列化（最小可用版） ---
    def _to_jsonable(self, obj: Any) -> Any:
        # BaseMessage 或 list[BaseMessage]
        try:
            if isinstance(obj, BaseMessage):
                return {"__type__": "lc_message_list", "data": messages_to_dict([obj])}
        except Exception:
            pass

        # NamedTuple-like（包括部分轻量对象）：使用 _asdict()
        try:
            if hasattr(obj, "_asdict") and callable(getattr(obj, "_asdict")):
                try:
                    mapping = obj._asdict()  # type: ignore[attr-defined]
                    return {"__type__": obj.__class__.__name__, "data": self._to_jsonable(dict(mapping))}
                except Exception:
                    pass
        except Exception:
            pass

        # 显式处理 LangGraph Send
        try:
            if LGSend is not None and isinstance(obj, LGSend):  # type: ignore[arg-type]
                node = getattr(obj, "node", getattr(obj, "name", None))
                arg = None
                for cand in ("arg", "state", "value", "args"):
                    if hasattr(obj, cand):
                        arg = getattr(obj, cand)
                        break
                return {"__type__": "Send", "node": node, "arg": self._to_jsonable(arg)}
        except Exception:
            pass

        # 兜底：按类名识别 Send（兼容不同包路径/实现）
        try:
            if getattr(obj.__class__, "__name__", "") == "Send":
                node = getattr(obj, "node", getattr(obj, "name", None))
                arg = None
                for cand in ("arg", "state", "value", "args"):
                    if hasattr(obj, cand):
                        arg = getattr(obj, cand)
                        break
                return {"__type__": "Send", "node": node, "arg": self._to_jsonable(arg)}
        except Exception:
            pass

        if isinstance(obj, list):
            # list[BaseMessage]
            try:
                if len(obj) == 0 or isinstance(obj[0], BaseMessage):
                    return {"__type__": "lc_message_list", "data": messages_to_dict(obj)}
            except Exception:
                pass
            return [self._to_jsonable(v) for v in obj]

        if isinstance(obj, dict):
            return {k: self._to_jsonable(v) for k, v in obj.items()}

        # 泛化：任意 Mapping（不止 dict）
        try:
            if isinstance(obj, Mapping):
                return {str(k): self._to_jsonable(v) for k, v in obj.items()}
        except Exception:
            pass

        # 泛化：任意 Sequence/Set（排除 str/bytes）
        try:
            if (isinstance(obj, (Sequence, Set)) and not isinstance(obj, (str, bytes, bytearray))):
                return [self._to_jsonable(v) for v in list(obj)]
        except Exception:
            pass

        if isinstance(obj, tuple):
            return {"__type__": "tuple", "data": [self._to_jsonable(v) for v in obj]}

        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj

        # 常见类型
        if isinstance(obj, datetime):
            return {"__type__": "datetime", "data": obj.isoformat()}
        if isinstance(obj, UUID):
            return {"__type__": "uuid", "data": str(obj)}

        # dataclass：使用 asdict 再递归
        try:
            if dataclasses.is_dataclass(obj):
                return {"__type__": obj.__class__.__name__, "data": self._to_jsonable(dataclasses.asdict(obj))}
        except Exception:
            pass

        # 一般对象（包括 langgraph.types.Send 等）：用 __dict__ 做浅序列化
        if hasattr(obj, "__dict__"):
            try:
                data = dict(obj.__dict__)
                # 兼容 Send：常见字段 name/args 或 channel/value
                return {"__type__": obj.__class__.__name__, "data": self._to_jsonable(data)}
            except Exception:
                pass

        # 最后兜底：转字符串（避免中断流式，后续可优化）
        try:
            return str(obj)
        except Exception:
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def _from_jsonable(self, obj: Any) -> Any:
        if isinstance(obj, dict) and "__type__" in obj:
            t = obj.get("__type__")
            if t == "lc_message_list":
                try:
                    return messages_from_dict(obj.get("data") or [])
                except Exception:
                    return []
            if t == "Send":
                # ========== 【关键修复】反序列化 Send 对象 ==========
                try:
                    if LGSend is not None:
                        node = obj.get("node")
                        arg = self._from_jsonable(obj.get("arg"))
                        return LGSend(node, arg)
                    else:
                        # 如果无法导入 Send，返回原始 dict（兜底）
                        return obj
                except Exception:
                    return obj
                # ====================================================
            if t == "tuple":
                data = obj.get("data") or []
                return tuple(self._from_jsonable(v) for v in data)
            if t == "datetime":
                try:
                    return datetime.fromisoformat(str(obj.get("data") or ""))
                except Exception:
                    return str(obj.get("data"))
            if t == "uuid":
                try:
                    return UUID(str(obj.get("data") or ""))
                except Exception:
                    return str(obj.get("data"))
            # 其他类型保持 data 的还原（尽量不丢失结构）
            data = obj.get("data")
            return self._from_jsonable(data)

        if isinstance(obj, dict):
            return {k: self._from_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._from_jsonable(v) for v in obj]
        return obj

    # --- 调试探针：定位不可 JSON 序列化的节点（仅在 CHECKPOINTER_DEBUG=1 时启用） ---
    def _probe_non_json(self, obj: Any, path: List[Any] = None, depth: int = 0, max_depth: int = 6, max_items: int = 50) -> List[str]:
        issues: List[str] = []
        if path is None:
            path = []
        if depth > max_depth:
            return issues
        # 快速尝试整体 dumps
        try:
            json.dumps(obj)
            return issues
        except Exception:
            pass
        # 递归细化
        if isinstance(obj, dict):
            cnt = 0
            for k, v in obj.items():
                if cnt >= max_items:
                    break
                issues += self._probe_non_json(v, path + [k], depth + 1, max_depth, max_items)
                cnt += 1
            if not issues:
                # 字典整体无法 dumps，记录类型
                issues.append(f"path={path} type=dict non-serializable")
        elif isinstance(obj, (list, tuple)):
            cnt = 0
            for i, v in enumerate(obj):
                if cnt >= max_items:
                    break
                issues += self._probe_non_json(v, path + [i], depth + 1, max_depth, max_items)
                cnt += 1
            if not issues:
                issues.append(f"path={path} type={'tuple' if isinstance(obj, tuple) else 'list'} non-serializable")
        else:
            # 对象或原子类型：记录其类型
            issues.append(f"path={path} type={type(obj).__name__} non-serializable")
        return issues
    
    async def aput(self, *args, **kwargs):
        """序列化后写入 checkpointer（签名与 LangGraph 调用保持兼容）"""
        try:
            # LangGraph 可能以位置参数或关键字参数传入 checkpoint / metadata / writes
            arglist = list(args)
            # 显式解析可能的 3/4 位置参数，避免错位
            config = kwargs.get('config') if 'config' in kwargs else (arglist[0] if len(arglist) >= 1 else None)
            checkpoint = kwargs.get('checkpoint') if 'checkpoint' in kwargs else (arglist[1] if len(arglist) >= 2 else None)
            metadata = kwargs.get('metadata') if 'metadata' in kwargs else (arglist[2] if len(arglist) >= 3 else None)
            new_versions = kwargs.get('new_versions') if 'new_versions' in kwargs else (arglist[3] if len(arglist) >= 4 else None)
            
            # aput 不接收 writes；writes 仅用于 aput_writes。这里不处理 writes，避免与 new_versions 混淆。

            debug = os.getenv('CHECKPOINTER_DEBUG', '0') == '1'
            
            if checkpoint is not None:
                # Checkpoint可能是dict或对象，统一用字典方式访问
                is_dict = isinstance(checkpoint, dict)
                
                # 处理 channel_values：统一使用_to_jsonable处理，移除双重序列化
                cv = checkpoint.get('channel_values') if is_dict else getattr(checkpoint, 'channel_values', {})
                if cv:
                    # 直接使用通用递归转换，_to_jsonable会正确处理BaseMessage
                    serialized_cv = self._to_jsonable(cv)
                    if is_dict:
                        checkpoint['channel_values'] = serialized_cv
                    else:
                        checkpoint.channel_values = serialized_cv
                
                # 处理 channel_versions（可能包含Send或其他不可序列化对象）
                try:
                    channel_versions = checkpoint.get('channel_versions') if is_dict else getattr(checkpoint, 'channel_versions', None)
                    if channel_versions:
                        processed = self._to_jsonable(channel_versions)
                        if is_dict:
                            checkpoint['channel_versions'] = processed
                        else:
                            checkpoint.channel_versions = processed
                except Exception:
                    pass
                
                # 处理 versions_seen（可能包含Send或其他不可序列化对象）
                try:
                    versions_seen = checkpoint.get('versions_seen') if is_dict else getattr(checkpoint, 'versions_seen', None)
                    if versions_seen:
                        processed = self._to_jsonable(versions_seen)
                        if is_dict:
                            checkpoint['versions_seen'] = processed
                        else:
                            checkpoint.versions_seen = processed
                except Exception:
                    pass

            # 处理 metadata：仅值做递归 JSON 化，保持键与结构
            if metadata is not None:
                try:
                    # 第一步：强制深度清理所有可能包含非序列化对象的字段
                    if isinstance(metadata, Mapping):
                        meta_tmp = dict(metadata)
                        # 清理顶层危险字段
                        dangerous_keys = ("writes", "tasks", "pending_writes", "commands", "task_path")
                        for k in dangerous_keys:
                            meta_tmp.pop(k, None)
                        
                        # 清理嵌套的writes（例如在某些子字段中）
                        for key, value in list(meta_tmp.items()):
                            if isinstance(value, dict):
                                for dk in dangerous_keys:
                                    value.pop(dk, None)
                        
                        metadata = meta_tmp
                    
                    # 第二步：递归JSON化所有值
                    metadata = self._to_jsonable(metadata)
                    
                except Exception as e:
                    # 失败时使用空字典而不是保留原metadata
                    metadata = {}

            # 构造严格白名单的 metadata 作为回退选项
            fallback_metadata = None
            try:
                allow_keys = ("source", "step", "parents")
                if isinstance(metadata, Mapping):
                    fallback_metadata = {k: metadata.get(k) for k in allow_keys if k in metadata}
                else:
                    fallback_metadata = None
            except Exception:
                fallback_metadata = None

            # 关键修复：将 config/new_versions 做递归 JSON 化，清除所有Send对象
            config_cleaned = config
            new_versions_cleaned = new_versions
            
            try:
                if config is not None:
                    config_cleaned = self._to_jsonable(config)
            except Exception as e:
                config_cleaned = config
            
            try:
                if new_versions is not None:
                    new_versions_cleaned = self._to_jsonable(new_versions)
            except Exception as e:
                new_versions_cleaned = new_versions

            # 处理 checkpoint.pending_writes（某些版本可能使用）
            try:
                is_dict = isinstance(checkpoint, dict)
                pending = checkpoint.get('pending_writes') if is_dict else getattr(checkpoint, 'pending_writes', None)
                if pending is not None:
                    pending_list = list(pending) if not isinstance(pending, list) else pending
                    for i, w in enumerate(pending_list):
                        try:
                            if isinstance(w, dict) and 'value' in w:
                                w['value'] = self._to_jsonable(w['value'])
                            elif hasattr(w, 'value'):
                                setattr(w, 'value', self._to_jsonable(getattr(w, 'value')))
                        except Exception:
                            continue
                    try:
                        if is_dict:
                            checkpoint['pending_writes'] = pending_list
                        else:
                            setattr(checkpoint, 'pending_writes', pending_list)
                    except Exception:
                        pass
            except Exception:
                pass

            # 关键修复：处理 checkpoint.pending_sends（Send对象列表，用于并行任务分发）
            try:
                is_dict = isinstance(checkpoint, dict)
                pending_sends = checkpoint.get('pending_sends') if is_dict else getattr(checkpoint, 'pending_sends', None)
                if pending_sends is not None and pending_sends:
                    serialized_sends = []
                    for send_obj in pending_sends:
                        try:
                            serialized_sends.append(self._to_jsonable(send_obj))
                        except Exception:
                            continue
                    # 关键：使用正确的方式赋值（dict用[]，对象用setattr）
                    try:
                        if is_dict:
                            checkpoint['pending_sends'] = serialized_sends
                        else:
                            setattr(checkpoint, 'pending_sends', serialized_sends)
                    except Exception as e:
                        print(f"[CheckpointerAdapter] Failed to set pending_sends: {e}")
            except Exception:
                pass

            # 不再改动 metadata（避免破坏 AsyncPostgresSaver 预期形状）；仅保留上方探针
            # if 需要，后续可针对 metadata 内具体路径做定点处理

            # 关键：以正确签名调用 aput，使用清理后的参数；失败时用白名单 metadata 回退重试一次
            try:
                if new_versions_cleaned is not None:
                    return await self.inner.aput(config_cleaned, checkpoint, metadata, new_versions_cleaned)
                else:
                    return await self.inner.aput(config_cleaned, checkpoint, metadata)
            except Exception as e:
                print(f"[CheckpointerAdapter] primary aput failed: {e}. Retrying with fallback metadata...")
                # 使用严格白名单的 metadata 回退
                fm = fallback_metadata if fallback_metadata is not None else {}
                if new_versions_cleaned is not None:
                    return await self.inner.aput(config_cleaned, checkpoint, fm, new_versions_cleaned)
                else:
                    return await self.inner.aput(config_cleaned, checkpoint, fm)
        except Exception as e:
            print(f"[CheckpointerAdapter] aput failed: {e}")
            raise

    async def aput_writes(self, *args, **kwargs):
        """包装 aput_writes：规范化 writes 的 value 为可 JSON 形态后转调底层。"""
        try:
            arglist = list(args)
            config = kwargs.get('config') if 'config' in kwargs else (arglist[0] if len(arglist) >= 1 else None)
            writes = kwargs.get('writes') if 'writes' in kwargs else (arglist[1] if len(arglist) >= 2 else None)
            task_id = kwargs.get('task_id') if 'task_id' in kwargs else (arglist[2] if len(arglist) >= 3 else None)
            task_path = kwargs.get('task_path') if 'task_path' in kwargs else (arglist[3] if len(arglist) >= 4 else "")

            norm_writes = []
            if isinstance(writes, (list, tuple)):
                for item in writes:
                    try:
                        if isinstance(item, (list, tuple)) and len(item) == 2:
                            ch, val = item
                            norm_writes.append((ch, self._to_jsonable(val)))
                        elif isinstance(item, dict) and 'channel' in item and 'value' in item:
                            norm_writes.append((item['channel'], self._to_jsonable(item['value'])))
                    except Exception:
                        continue

            # 以位置参数调用，最大兼容
            return await self.inner.aput_writes(config, norm_writes, task_id, task_path)
        except Exception as e:
            print(f"[CheckpointerAdapter] aput_writes failed: {e}")
            raise
    
    async def aget_tuple(self, *args, **kwargs):
        """从 checkpointer 读取 CheckpointTuple 并反序列化 - 这是 LangGraph 实际调用的方法！"""
        try:
            result = await self.inner.aget_tuple(*args, **kwargs)
            if result is None:
                return result
            
            # CheckpointTuple 包含 checkpoint, config, metadata, parent_config, pending_writes
            # 我们需要反序列化 checkpoint.channel_values 和 pending_sends
            try:
                # 获取 checkpoint（可能是属性或字典键）
                if hasattr(result, 'checkpoint'):
                    checkpoint = result.checkpoint
                elif isinstance(result, dict):
                    checkpoint = result.get('checkpoint')
                else:
                    checkpoint = None
                
                if checkpoint:
                    # 反序列化 channel_values
                    if isinstance(checkpoint, dict):
                        cv = checkpoint.get('channel_values')
                        if cv:
                            checkpoint['channel_values'] = self._from_jsonable(cv)
                        
                        # 反序列化 pending_sends
                        ps = checkpoint.get('pending_sends')
                        if ps and isinstance(ps, list):
                            checkpoint['pending_sends'] = [self._from_jsonable(s) for s in ps]
                    elif hasattr(checkpoint, 'channel_values'):
                        cv = checkpoint.channel_values
                        if cv:
                            checkpoint.channel_values = self._from_jsonable(cv)
                        
                        ps = getattr(checkpoint, 'pending_sends', None)
                        if ps and isinstance(ps, list):
                            checkpoint.pending_sends = [self._from_jsonable(s) for s in ps]
            except Exception as e:
                print(f"[CheckpointerAdapter] aget_tuple deserialization failed: {e}")
                import traceback
                traceback.print_exc()
            
            return result
        except Exception as e:
            print(f"[CheckpointerAdapter] aget_tuple failed: {e}")
            raise
    
    async def aget(self, *args, **kwargs):
        """从 checkpointer 读取并反序列化（签名与 LangGraph 调用保持兼容）"""
        try:
            result = await self.inner.aget(*args, **kwargs)
            if result is None:
                return result
            
            # 兼容不同返回结构：dict 或对象
            if isinstance(result, dict):
                cv = result.get('channel_values')
                if cv:
                    # 统一使用通用反序列化，_from_jsonable会正确处理lc_message_list
                    cv = self._from_jsonable(cv)
                    result['channel_values'] = cv
                
                # 反序列化 pending_sends
                pending_sends = result.get('pending_sends')
                if pending_sends:
                    deserialized_sends = []
                    for send_obj in pending_sends:
                        # 反序列化每个 pending_send
                        deserialized_sends.append(self._from_jsonable(send_obj))
                    result['pending_sends'] = deserialized_sends
                
            else:
                cv = getattr(result, 'channel_values', None)
                if cv is not None:
                    # 统一使用通用反序列化
                    cv = self._from_jsonable(cv)
                    setattr(result, 'channel_values', cv)
                
                # 反序列化 pending_sends（对象版）
                pending_sends = getattr(result, 'pending_sends', None)
                if pending_sends:
                    deserialized_sends = []
                    for send_obj in pending_sends:
                        # 反序列化每个 pending_send
                        deserialized_sends.append(self._from_jsonable(send_obj))
                    setattr(result, 'pending_sends', deserialized_sends)
            
            return result
        except Exception as e:
            print(f"[CheckpointerAdapter] aget failed: {e}")
            raise
    
    # 确保上下文管理器方法也被透传
    async def __aenter__(self):
        if hasattr(self.inner, '__aenter__'):
            await self.inner.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self.inner, '__aexit__'):
            return await self.inner.__aexit__(exc_type, exc_val, exc_tb)

    # Fallback attribute forwarding to inner for any methods not explicitly wrapped
    def __getattr__(self, name: str):
        return getattr(self.inner, name)
