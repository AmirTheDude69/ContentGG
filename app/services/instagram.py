from __future__ import annotations

import re
from typing import Iterable

import httpx

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
)

REEL_ID_PATTERN = re.compile(r'(?:https?://(?:www\.)?instagram\.com)?/reel/([A-Za-z0-9_-]+)')


class InstagramScrapeError(Exception):
    pass


def canonicalize_reel_url(reel_id: str) -> str:
    return f'https://www.instagram.com/reel/{reel_id}/'


def extract_reel_urls(html: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in REEL_ID_PATTERN.finditer(html):
        reel_id = match.group(1)
        url = canonicalize_reel_url(reel_id)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def cookie_header_to_dict(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in cookie_header.split(';'):
        part = item.strip()
        if not part or '=' not in part:
            continue
        key, value = part.split('=', 1)
        cookies[key.strip()] = value.strip()
    return cookies


class InstagramSavedFolderClient:
    def __init__(self, session_cookie_header: str, timeout_seconds: float = 30.0) -> None:
        self._session_cookie_header = session_cookie_header
        self._timeout_seconds = timeout_seconds

    async def fetch_saved_reels(self, saved_folder_url: str) -> list[str]:
        headers = {
            'user-agent': DEFAULT_USER_AGENT,
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
        }
        if self._session_cookie_header.strip():
            headers['cookie'] = self._session_cookie_header.strip()

        async with httpx.AsyncClient(follow_redirects=True, timeout=self._timeout_seconds) as client:
            response = await client.get(saved_folder_url, headers=headers)

        if response.status_code != 200:
            raise InstagramScrapeError(f'Instagram fetch failed with status {response.status_code}')

        urls = extract_reel_urls(response.text)
        if not urls:
            raise InstagramScrapeError('No reel URLs found. Session cookie may be expired or blocked.')
        return urls
