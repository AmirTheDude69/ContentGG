from __future__ import annotations

import re
from dataclasses import dataclass

REEL_PATTERN = re.compile(r'https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?')


@dataclass
class BotCommand:
    name: str
    argument: str


def parse_bot_command(text: str) -> BotCommand:
    text = text.strip()
    if not text.startswith('/'):
        return BotCommand(name='unknown', argument=text)

    pieces = text.split(maxsplit=1)
    name = pieces[0].split('@', 1)[0].lower()
    argument = pieces[1].strip() if len(pieces) > 1 else ''
    return BotCommand(name=name, argument=argument)


def extract_reel_url(text: str) -> str | None:
    match = REEL_PATTERN.search(text)
    if not match:
        return None
    url = match.group(0)
    return url if url.endswith('/') else f'{url}/'
