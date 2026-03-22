from __future__ import annotations

from typing import Iterable

import httpx


class TelegramApiError(Exception):
    pass


class TelegramClient:
    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._base_url = f'https://api.telegram.org/bot{bot_token}'

    async def set_webhook(self, webhook_url: str) -> None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f'{self._base_url}/setWebhook',
                json={'url': webhook_url, 'drop_pending_updates': False},
            )
        self._raise_if_failed(response)

    async def send_message(self, chat_id: int, text: str) -> None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f'{self._base_url}/sendMessage',
                json={
                    'chat_id': chat_id,
                    'text': text,
                    'disable_web_page_preview': True,
                },
            )
        self._raise_if_failed(response)

    async def broadcast(self, chat_ids: Iterable[int], text: str) -> None:
        for chat_id in chat_ids:
            try:
                await self.send_message(chat_id, text)
            except Exception:
                # Continue notifying remaining chats even if one fails.
                continue

    @staticmethod
    def _raise_if_failed(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise TelegramApiError(f'Telegram API error ({response.status_code}): {response.text}')
