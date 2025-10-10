"""
PostgreSQL-backed minimal persistence for threads and messages.

This module is intentionally small and framework-agnostic. It exposes a few
async functions that server.py can call at natural hook points without changing
route contracts.
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

import asyncpg
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from ..core.config import settings


_pool: Optional[asyncpg.Pool] = None
_init_lock = asyncio.Lock()


async def _ensure_pool() -> asyncpg.Pool:
    if settings.pg_dsn is None or settings.pg_dsn.strip() == "":
        raise RuntimeError("PG_DSN is not configured")
    global _pool
    if _pool is not None:
        return _pool
    async with _init_lock:
        if _pool is None:
            dsn = _normalize_dsn_for_asyncpg(settings.pg_dsn)
            _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
            await _verify_schema(_pool)
    return _pool


def _normalize_dsn_for_asyncpg(dsn: str) -> str:
    """
    Normalize DSN for asyncpg:
    - Replace scheme 'postgresql+psycopg://' with 'postgresql://'
    - Remove libpq-only keepalive params not understood by asyncpg/server
      (keepalives, keepalives_idle, keepalives_interval, keepalives_count)
    - Preserve other query params (e.g., sslmode, application_name)
    """
    try:
        if dsn.startswith("postgresql+psycopg://"):
            dsn = "postgresql://" + dsn[len("postgresql+psycopg://"):]
        parts = urlsplit(dsn)
        if parts.query:
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            filtered = []
            skip = {"keepalives", "keepalives_idle", "keepalives_interval", "keepalives_count"}
            for k, v in pairs:
                if k in skip:
                    continue
                filtered.append((k, v))
            new_query = urlencode(filtered)
            dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
        return dsn
    except Exception:
        # Best-effort: return original if parsing fails
        return dsn


async def _verify_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select
              to_regclass('public.threads')          as threads_exists,
              to_regclass('public.thread_messages')  as thread_messages_exists
            """
        )
        if not row or (row["threads_exists"] is None) or (row["thread_messages_exists"] is None):
            raise RuntimeError(
                "Database schema missing required tables (threads, thread_messages). "
                "Please run Prisma migrations first: `npx prisma migrate deploy` in frontend0917."
            )


async def ensure_thread(thread_id: str, user_id: Optional[str]) -> None:
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        if user_id:
            await conn.execute("select set_config('app.user_id', $1, true)", user_id)
        await conn.execute(
            """
            insert into threads(id, user_id) values($1, $2)
            on conflict (id) do update set updated_at = now(), user_id = coalesce(threads.user_id, excluded.user_id);
            """,
            thread_id,
            user_id,
        )


async def insert_message(thread_id: str, role: str, content: Dict[str, Any], user_id: Optional[str]) -> None:
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        if user_id:
            await conn.execute("select set_config('app.user_id', $1, true)", user_id)
        # Ensure thread exists, then insert message
        async with conn.transaction():
            await conn.execute(
                """
                insert into threads(id, user_id) values($1, $2)
                on conflict (id) do update set updated_at = now(), user_id = coalesce(threads.user_id, excluded.user_id);
                """,
                thread_id,
                user_id,
            )
            payload = json.dumps(content, ensure_ascii=False)
            await conn.execute(
                """
                insert into thread_messages(thread_id, role, content, user_id) values($1, $2, $3::jsonb, $4);
                """,
                thread_id,
                role,
                payload,
                user_id,
            )
            await conn.execute(
                """
                update threads set updated_at = now() where id = $1 and user_id = $2;
                """,
                thread_id,
                user_id,
            )


async def load_messages(thread_id: str, user_id: Optional[str]) -> List[Dict[str, Any]]:
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        if user_id:
            await conn.execute("select set_config('app.user_id', $1, true)", user_id)
        rows = await conn.fetch(
            """
            select tm.id, tm.role, tm.content, tm.created_at
            from thread_messages tm
            join threads t on t.id = tm.thread_id
            where tm.thread_id = $1 and t.user_id = $2
            order by tm.created_at asc, tm.id asc;
            """,
            thread_id,
            user_id,
        )
        return [dict(r) for r in rows]


async def delete_thread(thread_id: str, user_id: Optional[str]) -> None:
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        if user_id:
            await conn.execute("select set_config('app.user_id', $1, true)", user_id)
        await conn.execute("delete from threads where id = $1 and user_id = $2", thread_id, user_id)


async def touch_thread(thread_id: str, user_id: Optional[str]) -> None:
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        if user_id:
            await conn.execute("select set_config('app.user_id', $1, true)", user_id)
        await conn.execute("update threads set updated_at = now() where id = $1 and user_id = $2", thread_id, user_id)


async def get_thread_owner(thread_id: str) -> Optional[str]:
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select user_id from threads where id = $1",
            thread_id,
        )
        if row is None:
            return None
        return row["user_id"]


