from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def connect_db() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=60,
        )
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema() -> None:
    pool = await connect_db()
    schema_sql = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    pool = await connect_db()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    pool = await connect_db()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args: Any) -> str:
    pool = await connect_db()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    pool = await connect_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
