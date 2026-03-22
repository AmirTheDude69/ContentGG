from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from app.models import ClaudeAnalysisResult, SheetUpsertResult
from app.services.datefmt import format_sheet_date

HEADER_ORDER = [
    'Data Added',
    'Concept',
    'Script',
    'Requirements',
    'Virality',
    'Feasibility',
    'Recording Time',
    'Status',
    'Link',
]


@dataclass
class SheetRowData:
    data_added: str
    concept: str
    script: str
    requirements: str
    virality: str
    feasibility: str
    recording_time: str
    status: str
    link: str


def find_row_by_link(rows: list[list[str]], link: str) -> int | None:
    for row_index, row in enumerate(rows, start=2):
        value = row[8].strip() if len(row) > 8 else ''
        if value == link:
            return row_index
    return None


def resolve_status(existing_status: str, incoming_status: str) -> str:
    existing = existing_status.strip()
    return existing if existing else incoming_status


def build_row_values(data: SheetRowData, existing_status: str = '') -> list[str]:
    status = resolve_status(existing_status, data.status)
    return [
        data.data_added,
        data.concept,
        data.script,
        data.requirements,
        data.virality,
        data.feasibility,
        data.recording_time,
        status,
        data.link,
    ]


class SheetsClient:
    def __init__(
        self,
        service_account_info: dict[str, Any],
        sheet_id: str,
        worksheet_name: str,
    ) -> None:
        self._service_account_info = service_account_info
        self._sheet_id = sheet_id
        self._worksheet_name = worksheet_name

    async def upsert_analysis_row(self, data: SheetRowData) -> SheetUpsertResult:
        return await asyncio.to_thread(self._upsert_sync, data)

    async def get_link_by_row(self, row_number: int) -> str | None:
        return await asyncio.to_thread(self._get_link_by_row_sync, row_number)

    def _worksheet(self):
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
        ]
        creds = Credentials.from_service_account_info(self._service_account_info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_key(self._sheet_id).worksheet(self._worksheet_name)

    def _upsert_sync(self, data: SheetRowData) -> SheetUpsertResult:
        ws = self._worksheet()
        rows = ws.get_all_values()
        if not rows:
            ws.append_row(HEADER_ORDER, value_input_option='USER_ENTERED')
            rows = [HEADER_ORDER]

        target_row = find_row_by_link(rows[1:], data.link)

        if target_row is not None:
            existing = rows[target_row - 1]
            existing_status = existing[7] if len(existing) > 7 else ''
            values = build_row_values(data, existing_status)
            ws.update(f'A{target_row}:I{target_row}', [values], value_input_option='USER_ENTERED')
            return SheetUpsertResult(action='updated', row_number=target_row)

        values = build_row_values(data)
        ws.append_row(values, value_input_option='USER_ENTERED')

        refreshed_rows = ws.get_all_values()
        appended_row = find_row_by_link(refreshed_rows[1:], data.link)
        if appended_row is None:
            appended_row = len(refreshed_rows)
        return SheetUpsertResult(action='appended', row_number=appended_row)

    def _get_link_by_row_sync(self, row_number: int) -> str | None:
        if row_number < 2:
            return None
        ws = self._worksheet()
        value = ws.acell(f'I{row_number}').value
        if not value:
            return None
        return value.strip()


def build_sheet_row_data(
    analysis: ClaudeAnalysisResult,
    reel_url: str,
    timezone_name: str,
    status_default: str = 'To Do',
) -> SheetRowData:
    return SheetRowData(
        data_added=format_sheet_date(datetime.now(timezone.utc), timezone_name),
        concept=analysis.concept,
        script=analysis.script,
        requirements=analysis.requirements,
        virality=analysis.virality,
        feasibility=analysis.feasibility,
        recording_time=analysis.recording_time,
        status=status_default,
        link=reel_url,
    )
