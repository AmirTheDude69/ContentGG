from __future__ import annotations

from dataclasses import dataclass

from app.models import SheetUpsertResult
from app.services.claude import ClaudeClient
from app.services.downloader import ReelDownloader
from app.services.sheets import SheetsClient, build_sheet_row_data


@dataclass
class ProcessorConfig:
    timezone: str
    instagram_session_cookie: str


class PipelineProcessor:
    def __init__(
        self,
        downloader: ReelDownloader,
        claude: ClaudeClient,
        sheets: SheetsClient,
        config: ProcessorConfig,
    ) -> None:
        self._downloader = downloader
        self._claude = claude
        self._sheets = sheets
        self._config = config

    async def process_reel(self, reel_url: str) -> SheetUpsertResult:
        download = await self._downloader.download_video(reel_url, cookie_header=self._config.instagram_session_cookie)
        try:
            analysis = await self._claude.analyze_video(download.file_path, reel_url)
            sheet_row = build_sheet_row_data(analysis, reel_url, timezone_name=self._config.timezone)
            return await self._sheets.upsert_analysis_row(sheet_row)
        finally:
            await self._downloader.cleanup(download)
