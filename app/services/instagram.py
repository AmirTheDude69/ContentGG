from __future__ import annotations

import re

import httpx

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
)

REEL_ID_PATTERN = re.compile(r'(?:https?://(?:www\.)?instagram\.com)?/reel/([A-Za-z0-9_-]+)')
COLLECTION_ID_PATTERN = re.compile(r'/saved/[^/]+/(\d+)/?')


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


def extract_collection_id(saved_folder_url: str) -> str | None:
    match = COLLECTION_ID_PATTERN.search(saved_folder_url)
    if not match:
        return None
    return match.group(1)


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
        api_urls = await self._fetch_saved_reels_via_private_api(saved_folder_url)
        if api_urls:
            return api_urls

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

    async def _fetch_saved_reels_via_private_api(self, saved_folder_url: str) -> list[str]:
        cookies = cookie_header_to_dict(self._session_cookie_header)
        session_id = cookies.get('sessionid')
        if not session_id:
            return []

        collection_id = extract_collection_id(saved_folder_url)
        if collection_id:
            api_url = f'https://i.instagram.com/api/v1/feed/collection/{collection_id}/'
        else:
            api_url = 'https://i.instagram.com/api/v1/feed/saved/posts/'

        headers = {
            'User-Agent': 'Instagram 219.0.0.12.117 Android',
            'Accept': '*/*',
            'X-IG-App-ID': '936619743392459',
            'X-Requested-With': 'XMLHttpRequest',
        }
        params: dict[str, str | int] = {'count': 50}

        urls: list[str] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            for _ in range(4):
                response = await client.get(
                    api_url,
                    headers=headers,
                    params=params,
                    cookies={'sessionid': session_id},
                )
                if response.status_code != 200:
                    break

                payload = response.json()
                for url in _extract_reels_from_private_payload(payload):
                    if url not in seen:
                        seen.add(url)
                        urls.append(url)

                if not payload.get('more_available'):
                    break
                next_max_id = payload.get('next_max_id')
                if not next_max_id:
                    break
                params['max_id'] = next_max_id

        return urls


def _extract_reels_from_private_payload(payload: dict) -> list[str]:
    items = payload.get('items')
    if not isinstance(items, list):
        return []

    urls: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        media = item.get('media')
        if not isinstance(media, dict):
            continue
        code = media.get('code')
        if not isinstance(code, str) or not code:
            continue

        media_type = media.get('media_type')
        product_type = str(media.get('product_type') or '')
        has_video_versions = isinstance(media.get('video_versions'), list)
        if media_type == 2 or product_type == 'clips' or has_video_versions:
            urls.append(canonicalize_reel_url(code))

    return urls
