import asyncio
from typing import Optional

from ..core.config import settings
import time
from types import SimpleNamespace

try:
    from graphiti_core import Graphiti  # type: ignore
except Exception as e:  # pragma: no cover
    Graphiti = None  # type: ignore


_client_lock = asyncio.Lock()
_graphiti_client: Optional["Graphiti"] = None


async def get_graphiti_client() -> "Graphiti":
    """Lazily initialize a singleton Graphiti client. Build indices once. No clear_data."""
    global _graphiti_client
    if _graphiti_client is not None:
        return _graphiti_client
    async with _client_lock:
        if _graphiti_client is not None:
            return _graphiti_client
        if Graphiti is None:
            raise RuntimeError("graphiti_core is not installed or import failed")
        uri = settings.neo4j_uri
        user = settings.neo4j_user
        password = settings.neo4j_password
        database = settings.neo4j_database or "neo4j"
        if not uri or not user or not password:
            raise RuntimeError("Missing NEO4J_* environment variables for Graphiti initialization")
        client = Graphiti(uri, user, password, database=database)  # type: ignore
        # Install tracing proxies on the underlying neo4j driver when TRACE is enabled
        try:
            if getattr(settings, "trace_events", False):
                drv = getattr(client, "driver", None)
                if drv is not None:
                    client.driver = _TracingDriverProxy(drv)  # type: ignore
        except Exception:
            # Non-fatal; continue without tracing
            pass
        await client.build_indices_and_constraints()
        _graphiti_client = client
        return _graphiti_client

# ===== Tracing proxies for Neo4j driver (debug-only; no behavior change) =====

class _TracingAsyncResultProxy:
    def __init__(self, result):
        self._result = result

    def __getattr__(self, item):
        return getattr(self._result, item)


class _TracingAsyncSessionProxy:
    def __init__(self, session):
        self._session = session

    # ---- core query API ----
    async def run(self, query, **parameters):  # type: ignore
        t0 = time.perf_counter()
        try:
            q_preview = (str(query)[:300] + "...") if len(str(query)) > 300 else str(query)
            try:
                if getattr(settings, "trace_events", False):
                    p_preview = {k: (str(v)[:120] + "...") if isinstance(v, str) and len(v) > 120 else v for k, v in (parameters or {}).items()}
                    print(f"[KG][driver.run] q='{q_preview}' params={p_preview}")
            except Exception:
                pass
            res = await self._session.run(query, **parameters)
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                if getattr(settings, "trace_events", False):
                    print(f"[KG][driver.run] done elapsed_ms={elapsed}")
            except Exception:
                pass
            return _TracingAsyncResultProxy(res)
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                print(f"[KG][driver.run] error elapsed_ms={elapsed} err={e}")
            except Exception:
                pass
            raise

    # ---- transaction-style APIs (wrap tx.run) ----
    async def begin_transaction(self, *args, **kwargs):  # type: ignore
        tx = await self._session.begin_transaction(*args, **kwargs)
        return _TracingTxProxy(tx)

    async def execute_read(self, uow, *args, **kwargs):  # type: ignore
        async def wrapped(tx, *a, **k):
            return await uow(_TracingTxProxy(tx), *a, **k)
        t0 = time.perf_counter()
        try:
            res = await self._session.execute_read(wrapped, *args, **kwargs)
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                if getattr(settings, "trace_events", False):
                    print(f"[KG][execute_read] done elapsed_ms={elapsed}")
            except Exception:
                pass
            return res
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                print(f"[KG][execute_read] error elapsed_ms={elapsed} err={e}")
            except Exception:
                pass
            raise

    async def execute_write(self, uow, *args, **kwargs):  # type: ignore
        async def wrapped(tx, *a, **k):
            return await uow(_TracingTxProxy(tx), *a, **k)
        t0 = time.perf_counter()
        try:
            res = await self._session.execute_write(wrapped, *args, **kwargs)
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                if getattr(settings, "trace_events", False):
                    print(f"[KG][execute_write] done elapsed_ms={elapsed}")
            except Exception:
                pass
            return res
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                print(f"[KG][execute_write] error elapsed_ms={elapsed} err={e}")
            except Exception:
                pass
            raise

    # legacy API names
    async def read_transaction(self, uow, *args, **kwargs):  # type: ignore
        return await self.execute_read(uow, *args, **kwargs)

    async def write_transaction(self, uow, *args, **kwargs):  # type: ignore
        return await self.execute_write(uow, *args, **kwargs)

    async def __aenter__(self):  # support async with
        return await self._session.__aenter__()

    async def __aexit__(self, exc_type, exc, tb):
        return await self._session.__aexit__(exc_type, exc, tb)

    def __getattr__(self, item):
        return getattr(self._session, item)


class _TracingDriverProxy:
    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):  # type: ignore
        try:
            if getattr(settings, "trace_events", False):
                print("[KG][driver] open session")
        except Exception:
            pass
        ses = self._driver.session(*args, **kwargs)
        return _TracingAsyncSessionProxy(ses)

    async def execute_query(self, *args, **kwargs):  # type: ignore
        t0 = time.perf_counter()
        try:
            q = args[0] if args else kwargs.get("query")
            q_preview = (str(q)[:300] + "...") if q else None
            try:
                if getattr(settings, "trace_events", False):
                    print(f"[KG][execute_query] q='{q_preview}'")
            except Exception:
                pass
            res = await self._driver.execute_query(*args, **kwargs)
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                if getattr(settings, "trace_events", False):
                    # res can be (records, summary, keys) tuple in v5
                    rows = 0
                    try:
                        if isinstance(res, tuple) and len(res) > 0 and hasattr(res[0], "__len__"):
                            rows = len(res[0])
                    except Exception:
                        pass
                    print(f"[KG][execute_query] done elapsed_ms={elapsed} rows={rows}")
            except Exception:
                pass
            return res
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                print(f"[KG][execute_query] error elapsed_ms={elapsed} err={e}")
            except Exception:
                pass
            raise

    def __getattr__(self, item):
        return getattr(self._driver, item)


class _TracingTxProxy:
    def __init__(self, tx):
        self._tx = tx

    async def run(self, query, **parameters):  # type: ignore
        t0 = time.perf_counter()
        try:
            q_preview = (str(query)[:300] + "...") if len(str(query)) > 300 else str(query)
            try:
                if getattr(settings, "trace_events", False):
                    p_preview = {k: (str(v)[:120] + "...") if isinstance(v, str) and len(v) > 120 else v for k, v in (parameters or {}).items()}
                    print(f"[KG][tx.run] q='{q_preview}' params={p_preview}")
            except Exception:
                pass
            res = await self._tx.run(query, **parameters)
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                if getattr(settings, "trace_events", False):
                    print(f"[KG][tx.run] done elapsed_ms={elapsed}")
            except Exception:
                pass
            return res
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                print(f"[KG][tx.run] error elapsed_ms={elapsed} err={e}")
            except Exception:
                pass
            raise

    def __getattr__(self, item):
        return getattr(self._tx, item)



