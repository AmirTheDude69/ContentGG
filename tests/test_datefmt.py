from datetime import datetime, timezone

from app.services.datefmt import format_sheet_date


def test_format_sheet_date_matches_expected_style() -> None:
    dt = datetime(2026, 3, 23, 2, 0, tzinfo=timezone.utc)
    assert format_sheet_date(dt, 'Asia/Bangkok') == 'March 23- Mon'
