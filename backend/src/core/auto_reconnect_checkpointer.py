import asyncio
import time
from typing import Any, Optional
from collections import defaultdict


class AutoReconnectCheckpointer:
    """
    A thin wrapper that provides automatic reconnection and proactive connection recycling
    around an async Postgres checkpointer (e.g., AsyncPostgresSaver).

    Usage:
        ckpt = AutoReconnectCheckpointer(dsn=settings.pg_dsn, connection_max_age=210)
        await ckpt.aput(...)

    Features:
    - Lazily establishes the connection on first use
    - Proactively recycles connections before they timeout (default: 210s based on network diagnostics)
    - On connection-related errors, reconnects and retries (up to 3 attempts by default)
    - Keeps setup() idempotent and runs it only once per process lifetime
    """

    def __init__(self, dsn: str, initial_saver: Any = None, *, max_retry: int = 3, connection_max_age: int = 210, setup_on_connect: bool = True):
        self._dsn: str = dsn
        self._saver: Any = initial_saver
        self._cm: Any = None
        self._setup_done: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()  # 连接管理锁
        self._write_locks: dict = defaultdict(asyncio.Lock)  # 写入锁（按 thread_id）
        self._max_retry: int = max_retry
        self._setup_on_connect: bool = setup_on_connect
        self._connection_max_age: int = connection_max_age
        self._connection_created_at: Optional[float] = None

    async def __aenter__(self):
        await self._ensure_saver()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Close current context manager if we own one
        try:
            if self._cm is not None:
                try:
                    await self._cm.__aexit__(exc_type, exc_val, exc_tb)
                finally:
                    self._cm = None
        finally:
            self._saver = None

    async def _connect(self) -> None:
        # Import lazily to avoid hard dependency at import time
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore
        
        # MinimalCheckpointerAdapter 会处理序列化，这里不需要传递 serde
        self._cm = AsyncPostgresSaver.from_conn_string(self._dsn)
        self._saver = await self._cm.__aenter__()
        self._connection_created_at = time.time()  # 记录连接创建时间
        
        if self._setup_on_connect and not self._setup_done:
            try:
                await self._saver.setup()  # idempotent
                self._setup_done = True
            except Exception as e:  # pragma: no cover
                try:
                    print(f"[AutoReconnect] setup() ignored error: {e}")
                except Exception:
                    pass

    async def _ensure_saver(self) -> None:
        # 检查连接是否过期（主动回收）
        if self._saver is not None and self._connection_created_at is not None:
            connection_age = time.time() - self._connection_created_at
            if connection_age > self._connection_max_age:
                try:
                    print(f"[AutoReconnect] 连接已使用 {connection_age:.1f} 秒，超过上限 {self._connection_max_age} 秒，主动回收...")
                except Exception:
                    pass
                async with self._lock:
                    # 双重检查，避免并发重连
                    if self._saver is not None and self._connection_created_at is not None:
                        current_age = time.time() - self._connection_created_at
                        if current_age > self._connection_max_age:
                            await self._reconnect_locked()
                return
        
        # 原有逻辑：首次连接
        if self._saver is None:
            async with self._lock:
                if self._saver is None:
                    await self._connect()

    def _extract_thread_id(self, *args, **kwargs) -> str:
        """
        从参数中提取 thread_id，用于细粒度锁。
        
        LangGraph checkpointer 的调用签名：
        - aput(checkpoint, metadata, config, ...)
        - aput_writes(checkpoint, metadata, task_id, config, ...)
        
        thread_id 通常在 config 的 configurable 中。
        """
        # 尝试从位置参数提取 config
        config = None
        if len(args) >= 3:  # aput: checkpoint, metadata, config
            config = args[2]
        elif len(args) >= 4:  # aput_writes: checkpoint, metadata, task_id, config
            config = args[3]
        
        # 尝试从关键字参数提取
        if config is None:
            config = kwargs.get("config")
        
        # 从 config 中提取 thread_id
        if isinstance(config, dict):
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id:
                return str(thread_id)
        
        # 如果没有找到，返回默认值
        return "default"
    
    def _is_connection_error(self, e: Exception) -> bool:
        msg = (str(e) or "").lower()
        # Heuristics for psycopg/SSL/pgbouncer disconnects
        needles = (
            "the connection is closed",
            "ssl syscall error",
            "eof detected",
            "connection reset",
            "bad length",
            "server closed the connection",
        )
        return any(n in msg for n in needles)

    async def _reconnect_locked(self) -> None:
        # Must be called under self._lock
        # Close previous CM if any
        try:
            if self._cm is not None:
                try:
                    await self._cm.__aexit__(None, None, None)
                finally:
                    self._cm = None
        except Exception:
            pass
        self._saver = None
        await self._connect()

    async def _with_retry(self, method_name: str, *args, **kwargs):
        """
        执行方法并自动重试（连接错误时）
        
        注意：不在此方法内调用 _ensure_saver()，因为：
        - aput/aput_writes 已在锁内调用了 _ensure_saver()
        - aget/aget_tuple 等读方法会自己调用
        """
        attempt = 0
        while True:
            try:
                method = getattr(self._saver, method_name)
                return await method(*args, **kwargs)
            except Exception as e:
                if not self._is_connection_error(e) or attempt >= self._max_retry:
                    raise
                try:
                    print(f"[AutoReconnect] {method_name} failed: {e}. Reconnecting and retrying...")
                except Exception:
                    pass
                async with self._lock:
                    await self._reconnect_locked()
                attempt += 1

    # Public async methods commonly used by LangGraph checkpointer
    async def aput(self, *args, **kwargs):
        """
        写入 checkpoint（带按 thread_id 的细粒度锁）
        
        锁的作用：
        - 同一 thread_id 内：串行写入（防止并发冲突）
        - 不同 thread_id 间：并行写入（性能无损）
        """
        thread_id = self._extract_thread_id(*args, **kwargs)
        write_lock = self._write_locks[thread_id]
        
        async with write_lock:
            # 在锁内检查连接状态，防止 race condition
            await self._ensure_saver()
            return await self._with_retry("aput", *args, **kwargs)

    async def aput_writes(self, *args, **kwargs):
        """
        写入 checkpoint writes（带按 thread_id 的细粒度锁）
        
        这是并发冲突的主要触发点：
        - SQL_Subgraph 和 Vector_Subgraph 并行完成后会同时调用此方法
        - 通过按 thread_id 加锁，确保同一会话内的写入串行化
        """
        thread_id = self._extract_thread_id(*args, **kwargs)
        write_lock = self._write_locks[thread_id]
        
        try:
            # 尝试获取锁（如果另一个写入正在进行，这里会等待）
            print(f"[AutoReconnect] aput_writes for thread={thread_id} acquiring lock...")
        except Exception:
            pass
        
        async with write_lock:
            try:
                print(f"[AutoReconnect] aput_writes for thread={thread_id} lock acquired, writing...")
            except Exception:
                pass
            
            # 在锁内检查连接状态，防止 race condition
            await self._ensure_saver()
            result = await self._with_retry("aput_writes", *args, **kwargs)
            
            try:
                print(f"[AutoReconnect] aput_writes for thread={thread_id} completed, releasing lock")
            except Exception:
                pass
            
            return result

    async def aget(self, *args, **kwargs):
        """读取 checkpoint（不需要写锁，但需要确保连接）"""
        print("⚡⚡⚡ [AutoReconnectCheckpointer] aget called! ⚡⚡⚡")
        await self._ensure_saver()
        return await self._with_retry("aget", *args, **kwargs)

    async def alist(self, *args, **kwargs):
        """列出 checkpoints（不需要写锁，但需要确保连接）"""
        await self._ensure_saver()
        return await self._with_retry("alist", *args, **kwargs)

    async def aget_tuple(self, *args, **kwargs):
        """读取 checkpoint tuple（不需要写锁，但需要确保连接）"""
        print("⚡⚡⚡ [AutoReconnectCheckpointer] aget_tuple called! ⚡⚡⚡")
        await self._ensure_saver()
        return await self._with_retry("aget_tuple", *args, **kwargs)

    # Fallback attribute proxying to inner saver for other optional methods/attrs
    def __getattr__(self, name: str) -> Any:
        saver = object.__getattribute__(self, "_saver")
        if saver is None:
            raise AttributeError(name)
        return getattr(saver, name)


