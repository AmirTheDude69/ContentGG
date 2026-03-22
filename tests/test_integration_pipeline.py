from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.models import ClaudeAnalysisResult, DownloadResult
from app.services.processor import PipelineProcessor, ProcessorConfig
from app.services.sheets import SheetRowData
from app.worker import JobWorker
from app.repositories import JobRecord


class FakeDownloader:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.cleaned: list[str] = []

    async def download_video(self, reel_url: str, cookie_header: str = '') -> DownloadResult:
        if self.should_fail:
            raise RuntimeError('download failed')
        return DownloadResult(reel_url=reel_url, file_path=Path('/tmp/fake.mp4'), title='fake')

    async def cleanup(self, result: DownloadResult) -> None:
        self.cleaned.append(result.reel_url)


class FakeClaude:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    async def analyze_video(self, _video_path: Path, _reel_url: str) -> ClaudeAnalysisResult:
        if self.should_fail:
            raise RuntimeError('claude failed')
        return ClaudeAnalysisResult(
            concept='concept',
            script='script',
            requirements='Outfit, Wallet',
            virality='High',
            feasibility='Easy',
            recording_time='<5',
        )


class InMemorySheets:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.rows: dict[str, SheetRowData] = {}

    async def upsert_analysis_row(self, data: SheetRowData):
        if self.should_fail:
            raise RuntimeError('sheets failed')
        action = 'updated' if data.link in self.rows else 'appended'
        self.rows[data.link] = data
        row_number = list(self.rows).index(data.link) + 2
        return type('Result', (), {'action': action, 'row_number': row_number})


@pytest.mark.asyncio
async def test_full_flow_and_duplicate_url_behavior() -> None:
    downloader = FakeDownloader()
    claude = FakeClaude()
    sheets = InMemorySheets()
    processor = PipelineProcessor(
        downloader=downloader,
        claude=claude,
        sheets=sheets,
        config=ProcessorConfig(timezone='Asia/Bangkok', instagram_session_cookie='sessionid=x'),
    )

    first = await processor.process_reel('https://www.instagram.com/reel/AAA111/')
    second = await processor.process_reel('https://www.instagram.com/reel/AAA111/')

    assert first.action == 'appended'
    assert second.action == 'updated'
    assert len(sheets.rows) == 1


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def broadcast(self, _chat_ids, text: str) -> None:
        self.messages.append(text)


@pytest.mark.asyncio
async def test_worker_notifies_on_download_claude_and_sheet_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_claimed(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    async def fake_fail_or_retry(*args, **kwargs):
        return 'retrying', 1

    async def fake_list_chats(*args, **kwargs):
        return [123]

    monkeypatch.setattr('app.worker.mark_saved_reel_error', noop)
    monkeypatch.setattr('app.worker.mark_saved_reel_processed', noop)
    monkeypatch.setattr('app.worker.complete_job', noop)
    monkeypatch.setattr('app.worker.fail_or_retry_job', fake_fail_or_retry)
    monkeypatch.setattr('app.worker.list_active_chats', fake_list_chats)

    job = JobRecord(
        id='00000000-0000-0000-0000-000000000000',
        reel_url='https://www.instagram.com/reel/ERR111/',
        trigger_source='manual_add',
        status='processing',
        attempts=0,
        max_attempts=3,
        payload={},
    )

    for fail_type in ('download', 'claude', 'sheets'):
        downloader = FakeDownloader(should_fail=fail_type == 'download')
        claude = FakeClaude(should_fail=fail_type == 'claude')
        sheets = InMemorySheets(should_fail=fail_type == 'sheets')

        processor = PipelineProcessor(
            downloader=downloader,
            claude=claude,
            sheets=sheets,
            config=ProcessorConfig(timezone='Asia/Bangkok', instagram_session_cookie='x'),
        )
        telegram = FakeTelegram()
        worker = JobWorker(processor=processor, telegram=telegram)

        await worker._handle_job(job)

        assert telegram.messages, f'Expected failure notification for {fail_type}'
        assert 'failed' in telegram.messages[-1].lower()
