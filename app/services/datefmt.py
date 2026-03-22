from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def format_sheet_date(dt: datetime, timezone: str) -> str:
    local_dt = dt.astimezone(ZoneInfo(timezone))
    return local_dt.strftime('%B %-d- %a')
