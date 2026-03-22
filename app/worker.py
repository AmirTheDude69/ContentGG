from __future__ import annotations

import asyncio
import logging

from app.repositories import (
    JobRecord,
    claim_next_job,
    complete_job,
    fail_or_retry_job,
    list_active_chats,
    mark_saved_reel_error,
    mark_saved_reel_processed,
)
from app.services.processor import PipelineProcessor
from app.services.telegram import TelegramClient

LOGGER = logging.getLogger(__name__)


class JobWorker:
    def __init__(self, processor: PipelineProcessor, telegram: TelegramClient) -> None:
        self._processor = processor
        self._telegram = telegram
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name='job-worker')

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            job = await claim_next_job()
            if job is None:
                await asyncio.sleep(2)
                continue

            await self._handle_job(job)

    async def _handle_job(self, job: JobRecord) -> None:
        try:
            result = await self._processor.process_reel(job.reel_url)
            await mark_saved_reel_processed(job.reel_url, sheet_row=result.row_number)
            await complete_job(job.id)
            await self._notify_success(job.reel_url, result.action, result.row_number)
        except Exception as exc:
            LOGGER.exception('Job failed for %s', job.reel_url)
            await mark_saved_reel_error(job.reel_url, str(exc))
            outcome, attempts = await fail_or_retry_job(job, str(exc))
            await self._notify_failure(job.reel_url, str(exc), outcome, attempts, job.max_attempts)

    async def _notify_success(self, reel_url: str, action: str, row_number: int) -> None:
        chats = await list_active_chats()
        if not chats:
            return
        text = (
            'ContentGG update complete.\n'
            f'- Action: {action}\n'
            f'- Row: {row_number}\n'
            f'- Link: {reel_url}'
        )
        await self._telegram.broadcast(chats, text)

    async def _notify_failure(
        self,
        reel_url: str,
        reason: str,
        outcome: str,
        attempts: int,
        max_attempts: int,
    ) -> None:
        chats = await list_active_chats()
        if not chats:
            return
        text = (
            'ContentGG processing failed.\n'
            f'- Link: {reel_url}\n'
            f'- Error: {reason[:300]}\n'
            f'- State: {outcome} ({attempts}/{max_attempts})'
        )
        await self._telegram.broadcast(chats, text)
