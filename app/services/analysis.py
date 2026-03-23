from __future__ import annotations

import json
import re
from typing import Any

from app.models import ClaudeAnalysisResult

# These must match Google Sheet dropdown values exactly.
VIRALITY_ALLOWED = ('High', 'Mid', 'Low')
FEASIBILITY_ALLOWED = ('Easy', 'Complex')
RECORDING_TIME_ALLOWED = ('<5', '5-10', '10-30')


class AnalysisNormalizationError(Exception):
    pass


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', text, flags=re.S)
    if not match:
        raise AnalysisNormalizationError('Claude response does not contain a JSON object')

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise AnalysisNormalizationError(f'Invalid JSON payload from Claude: {exc}') from exc

    if not isinstance(payload, dict):
        raise AnalysisNormalizationError('Claude payload is not a JSON object')
    return payload


def normalize_virality(value: str) -> str:
    lowered = value.lower().strip()
    if lowered in {'high', 'very high', 'viral', 'very viral'}:
        return 'High'
    if lowered in {'medium', 'mid', 'average', 'moderate'}:
        return 'Mid'
    if lowered in {'low', 'very low'}:
        return 'Low'
    return 'Mid'


def normalize_feasibility(value: str) -> str:
    lowered = value.lower().strip()
    if lowered in {'easy', 'low', 'simple', 'beginner'}:
        return 'Easy'
    if lowered in {'medium', 'moderate'}:
        return 'Complex'
    if lowered in {'hard', 'difficult', 'complex', 'advanced'}:
        return 'Complex'
    return 'Complex'


def normalize_recording_time(value: str) -> str:
    lowered = value.lower().strip()
    if any(token in lowered for token in ('<5', 'under 5', '1-5', 'less than 5')):
        return '<5'
    if any(
        token in lowered
        for token in ('5-10', '5 to 10', '6-10', 'about 10', 'around 10', '10 min', '10 mins', '10 minutes')
    ):
        return '5-10'
    if any(token in lowered for token in ('10-30', 'over 10', '>10', 'more than 10', '15+', 'over 15', '>15')):
        return '10-30'
    minutes_match = re.search(r'(\d+)\s*(?:min|mins|minute|minutes)', lowered)
    if minutes_match:
        minutes = int(minutes_match.group(1))
        if minutes <= 5:
            return '<5'
        if minutes <= 10:
            return '5-10'
        return '10-30'
    return '5-10'


def normalize_requirements(value: str) -> str:
    compact = value.replace('\n', ',')
    compact = re.sub(r'[*\-]+', '', compact)
    parts = [part.strip() for part in compact.split(',') if part.strip()]
    if not parts:
        return 'Phone, basic setup'
    return ', '.join(parts[:8])


def parse_and_normalize_analysis(raw_text: str) -> ClaudeAnalysisResult:
    payload = parse_json_object(raw_text)
    concept = str(payload.get('concept', '')).strip()
    script = str(payload.get('script', '')).strip()
    requirements = normalize_requirements(str(payload.get('requirements', '')).strip())
    virality = normalize_virality(str(payload.get('virality', '')))
    feasibility = normalize_feasibility(str(payload.get('feasibility', '')))
    recording_time = normalize_recording_time(str(payload.get('recording_time', '')))

    if not concept:
        raise AnalysisNormalizationError('Missing concept in Claude response')
    if not script:
        raise AnalysisNormalizationError('Missing script in Claude response')

    return ClaudeAnalysisResult(
        concept=concept,
        script=script,
        requirements=requirements,
        virality=virality,
        feasibility=feasibility,
        recording_time=recording_time,
    )
