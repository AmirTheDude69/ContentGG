from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.models import PollResult
from app.repositories import (
    create_poll_run,
    enqueue_job,
    finalize_poll_run,
    has_saved_reel,
    has_successful_poll,
)
from app.services.instagram import InstagramSavedFolderClient


class SavedFolderPoller:
    def __init__(self, settings: Settings, instagram_client: InstagramSavedFolderClient) -> None:
        self._settings = settings
        self._instagram = instagram_client

    async def run_once(self, trigger_source: str) -> PollResult:
        poll_run_id = await create_poll_run(trigger_source)
        fetched_count = 0
        considered_count = 0
        enqueued_count = 0

        try:
            urls = await self._instagram.fetch_saved_reels(self._settings.instagram_saved_folder_url)
            fetched_count = len(urls)
            has_success = await has_successful_poll()

            considered_urls = urls if has_success else urls[: self._settings.poll_backfill_limit]
            considered_count = len(considered_urls)

            for url in considered_urls:
                if await has_saved_reel(url):
                    continue
                inserted = await enqueue_job(
                    reel_url=url,
                    trigger_source='saved_folder',
                    max_attempts=self._settings.retry_max_attempts,
                )
                if inserted:
                    enqueued_count += 1

            await finalize_poll_run(
                poll_run_id,
                status='success',
                fetched_count=fetched_count,
                considered_count=considered_count,
                enqueued_count=enqueued_count,
                error=None,
            )
            return PollResult(
                fetched_count=fetched_count,
                considered_count=considered_count,
                enqueued_count=enqueued_count,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            await finalize_poll_run(
                poll_run_id,
                status='failed',
                fetched_count=fetched_count,
                considered_count=considered_count,
                enqueued_count=enqueued_count,
                error=str(exc),
            )
            raise
