from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app import db


@dataclass
class JobRecord:
    id: str
    reel_url: str
    trigger_source: str
    status: str
    attempts: int
    max_attempts: int
    payload: dict[str, Any]


async def upsert_saved_reel(reel_url: str, source_mode: str = 'saved_folder') -> None:
    await db.execute(
        """
        insert into saved_reels (reel_url, source_mode)
        values ($1, $2)
        on conflict (reel_url)
        do update set updated_at = now()
        """,
        reel_url,
        source_mode,
    )


async def mark_saved_reel_processed(reel_url: str, sheet_row: int) -> None:
    await db.execute(
        """
        update saved_reels
        set status = 'processed',
            sheet_row = $2,
            last_processed_at = now(),
            last_error = null,
            updated_at = now()
        where reel_url = $1
        """,
        reel_url,
        sheet_row,
    )


async def mark_saved_reel_error(reel_url: str, error: str) -> None:
    await db.execute(
        """
        update saved_reels
        set status = 'error',
            last_error = left($2, 1000),
            updated_at = now()
        where reel_url = $1
        """,
        reel_url,
        error,
    )


async def enqueue_job(reel_url: str, trigger_source: str, max_attempts: int, payload: dict[str, Any] | None = None) -> bool:
    payload = payload or {}
    await upsert_saved_reel(reel_url, source_mode=trigger_source)
    try:
        await db.execute(
            """
            insert into jobs (reel_url, trigger_source, status, attempts, max_attempts, payload)
            values ($1, $2, 'pending', 0, $3, $4::jsonb)
            """,
            reel_url,
            trigger_source,
            max_attempts,
            json.dumps(payload),
        )
        return True
    except Exception as exc:
        if 'jobs_active_url_idx' in str(exc) or 'duplicate key value violates unique constraint' in str(exc):
            return False
        raise


async def claim_next_job() -> JobRecord | None:
    async with db.transaction() as conn:
        row = await conn.fetchrow(
            """
            with next_job as (
              select id
              from jobs
              where status = 'pending' and next_attempt_at <= now()
              order by created_at asc
              limit 1
              for update skip locked
            )
            update jobs as j
            set status = 'processing',
                updated_at = now()
            from next_job
            where j.id = next_job.id
            returning j.id::text, j.reel_url, j.trigger_source, j.status, j.attempts, j.max_attempts, j.payload
            """
        )
        if row is None:
            return None
        return JobRecord(
            id=row['id'],
            reel_url=row['reel_url'],
            trigger_source=row['trigger_source'],
            status=row['status'],
            attempts=row['attempts'],
            max_attempts=row['max_attempts'],
            payload=row['payload'] or {},
        )


async def complete_job(job_id: str) -> None:
    await db.execute(
        """
        update jobs
        set status = 'completed', updated_at = now()
        where id = $1::uuid
        """,
        job_id,
    )


async def fail_or_retry_job(job: JobRecord, error: str) -> tuple[str, int]:
    attempts = job.attempts + 1
    if attempts < job.max_attempts:
        delay_minutes = min(30, 2 ** attempts)
        await db.execute(
            """
            update jobs
            set status = 'pending',
                attempts = $2,
                last_error = left($3, 1000),
                next_attempt_at = now() + ($4::text || ' minutes')::interval,
                updated_at = now()
            where id = $1::uuid
            """,
            job.id,
            attempts,
            error,
            delay_minutes,
        )
        return 'retrying', attempts

    await db.execute(
        """
        update jobs
        set status = 'failed',
            attempts = $2,
            last_error = left($3, 1000),
            updated_at = now()
        where id = $1::uuid
        """,
        job.id,
        attempts,
        error,
    )
    return 'failed', attempts


async def add_or_update_chat(chat_id: int, user_id: int | None, username: str | None) -> None:
    await db.execute(
        """
        insert into bot_chats (chat_id, user_id, username, is_active)
        values ($1, $2, $3, true)
        on conflict (chat_id)
        do update set user_id = excluded.user_id,
                      username = excluded.username,
                      is_active = true,
                      updated_at = now()
        """,
        chat_id,
        user_id,
        username,
    )


async def list_active_chats() -> list[int]:
    rows = await db.fetch(
        """
        select chat_id
        from bot_chats
        where is_active = true
        order by created_at asc
        """
    )
    return [int(row['chat_id']) for row in rows]


async def queue_stats() -> dict[str, int]:
    rows = await db.fetch(
        """
        select status, count(*)::int as c
        from jobs
        group by status
        """
    )
    stats = {'pending': 0, 'processing': 0, 'completed': 0, 'failed': 0}
    for row in rows:
        stats[row['status']] = row['c']
    return stats


async def list_recent_jobs(limit: int = 5) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select id::text, reel_url, status, trigger_source, attempts, updated_at
        from jobs
        order by updated_at desc
        limit $1
        """,
        limit,
    )
    return [
        {
            'id': row['id'],
            'reel_url': row['reel_url'],
            'status': row['status'],
            'trigger_source': row['trigger_source'],
            'attempts': row['attempts'],
            'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
        }
        for row in rows
    ]


async def create_poll_run(trigger_source: str) -> int:
    row = await db.fetchrow(
        """
        insert into poll_runs (trigger_source, status)
        values ($1, 'running')
        returning id
        """,
        trigger_source,
    )
    assert row is not None
    return int(row['id'])


async def finalize_poll_run(
    poll_run_id: int,
    status: str,
    fetched_count: int,
    considered_count: int,
    enqueued_count: int,
    error: str | None = None,
) -> None:
    await db.execute(
        """
        update poll_runs
        set status = $2,
            fetched_count = $3,
            considered_count = $4,
            enqueued_count = $5,
            error = $6,
            completed_at = now()
        where id = $1
        """,
        poll_run_id,
        status,
        fetched_count,
        considered_count,
        enqueued_count,
        error,
    )


async def has_successful_poll() -> bool:
    row = await db.fetchrow(
        """
        select 1
        from poll_runs
        where status = 'success'
        limit 1
        """
    )
    return row is not None


async def has_saved_reel(reel_url: str) -> bool:
    row = await db.fetchrow('select 1 from saved_reels where reel_url = $1', reel_url)
    return row is not None


async def last_poll_summary() -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        select id, trigger_source, status, fetched_count, considered_count, enqueued_count, error, started_at, completed_at
        from poll_runs
        order by id desc
        limit 1
        """
    )
    if row is None:
        return None
    return {
        'id': int(row['id']),
        'trigger_source': row['trigger_source'],
        'status': row['status'],
        'fetched_count': int(row['fetched_count']),
        'considered_count': int(row['considered_count']),
        'enqueued_count': int(row['enqueued_count']),
        'error': row['error'],
        'started_at': row['started_at'].isoformat() if row['started_at'] else None,
        'completed_at': row['completed_at'].isoformat() if row['completed_at'] else None,
    }
