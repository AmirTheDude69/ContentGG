from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ClaudeAnalysisResult:
    concept: str
    script: str
    requirements: str
    virality: str
    feasibility: str
    recording_time: str


@dataclass
class DownloadResult:
    reel_url: str
    file_path: Path
    title: str


@dataclass
class SheetUpsertResult:
    action: str
    row_number: int


@dataclass
class PollResult:
    fetched_count: int
    considered_count: int
    enqueued_count: int
    completed_at: datetime
