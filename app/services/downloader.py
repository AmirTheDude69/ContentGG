from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from urllib.parse import urlparse
from uuid import uuid4

from yt_dlp import YoutubeDL

from app.models import DownloadResult
from app.services.instagram import cookie_header_to_dict

IGNORE_SUFFIXES = {'.part', '.ytdl', '.temp'}


class DownloadError(Exception):
    pass


class ReelDownloader:
    """Reuses the Just-Fetch yt-dlp approach, adapted for single-reel video downloads."""

    def __init__(self, temp_root: Path | None = None) -> None:
        self._temp_root = temp_root or (Path(tempfile.gettempdir()) / 'contentgg')
        self._temp_root.mkdir(parents=True, exist_ok=True)

    async def download_video(self, reel_url: str, cookie_header: str = '') -> DownloadResult:
        batch_dir = Path(tempfile.mkdtemp(prefix='contentgg-', dir=self._temp_root))
        cookie_file: Path | None = None
        try:
            if cookie_header.strip():
                cookie_text = cookie_header_to_netscape(cookie_header)
                cookie_file = batch_dir / 'cookies.txt'
                cookie_file.write_text(cookie_text, encoding='utf-8')

            file_path, title = await asyncio.to_thread(
                self._download_single,
                reel_url,
                batch_dir,
                cookie_file,
            )
            return DownloadResult(reel_url=reel_url, file_path=file_path, title=title)
        except Exception as exc:
            await asyncio.to_thread(rmtree, batch_dir, True)
            raise DownloadError(str(exc)) from exc

    async def cleanup(self, result: DownloadResult) -> None:
        if result.file_path.exists():
            await asyncio.to_thread(result.file_path.unlink)
        parent = result.file_path.parent
        if parent.exists():
            await asyncio.to_thread(rmtree, parent, True)

    def _download_single(
        self,
        reel_url: str,
        output_dir: Path,
        cookie_file: Path | None,
    ) -> tuple[Path, str]:
        prefix = uuid4().hex
        outtmpl = str(output_dir / f'{prefix}-%(id)s.%(ext)s')
        options: dict[str, object] = {
            'format': 'bv*+ba/b',
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'restrictfilenames': True,
            'retries': 3,
            'fragment_retries': 3,
            'concurrent_fragment_downloads': 1,
            'noplaylist': True,
            'ignoreerrors': False,
            'nooverwrites': True,
            'writethumbnail': False,
            'writeinfojson': False,
            'writedescription': False,
            'writesubtitles': False,
        }
        if cookie_file is not None:
            options['cookiefile'] = str(cookie_file)

        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(reel_url, download=True)
            if not isinstance(info, dict):
                raise DownloadError('yt-dlp returned invalid metadata')

        candidates = [
            path
            for path in output_dir.glob(f'{prefix}-*')
            if path.is_file() and path.suffix not in IGNORE_SUFFIXES
        ]
        if not candidates:
            raise DownloadError('No downloaded media file found')

        selected = sorted(candidates, key=lambda p: p.stat().st_size, reverse=True)[0]
        title = str(info.get('title') or urlparse(reel_url).path.strip('/'))
        return selected, title


def cookie_header_to_netscape(cookie_header: str) -> str:
    cookies = cookie_header_to_dict(cookie_header)
    if not cookies:
        return '# Netscape HTTP Cookie File\n'

    lines = ['# Netscape HTTP Cookie File']
    for key, value in cookies.items():
        lines.append(f'.instagram.com\tTRUE\t/\tTRUE\t2147483647\t{key}\t{value}')
    return '\n'.join(lines) + '\n'
