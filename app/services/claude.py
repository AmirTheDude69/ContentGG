from __future__ import annotations

import base64
import mimetypes
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.models import ClaudeAnalysisResult
from app.services.analysis import parse_and_normalize_analysis


class ClaudeAnalysisError(Exception):
    pass


class ClaudeClient:
    def __init__(self, api_key: str, model: str, style_guide_text: str) -> None:
        self._api_key = api_key
        self._model = model
        self._style_guide_text = style_guide_text

    async def analyze_video(self, video_path: Path, reel_url: str) -> ClaudeAnalysisResult:
        try:
            return await self._analyze_with_video_input(video_path, reel_url)
        except ClaudeAnalysisError as exc:
            # Anthropic may reject video content blocks for some accounts/models.
            if _is_unsupported_video_input_error(str(exc)):
                return await self._analyze_with_keyframes(video_path, reel_url)
            raise

    async def _analyze_with_video_input(self, video_path: Path, reel_url: str) -> ClaudeAnalysisResult:
        media_type = mimetypes.guess_type(video_path.name)[0] or 'video/mp4'
        payload = base64.b64encode(video_path.read_bytes()).decode('utf-8')

        prompt = (
            'Analyze this Instagram reel and output ONLY JSON with keys: '
            'concept, script, requirements, virality, feasibility, recording_time.\n\n'
            'Rules:\n'
            '- requirements must be concise comma-separated assets/needs\n'
            '- virality should map to High/Medium/Low\n'
            '- feasibility should map to Easy/Medium/Hard\n'
            '- recording_time should map to <5 / 5-15 / 15+\n'
            '- script should be practical and short for recreating video style\n\n'
            f'Reel URL: {reel_url}\n\n'
            'Creator style guide:\n'
            f'{self._style_guide_text}'
        )

        body = {
            'model': self._model,
            'max_tokens': 1400,
            'temperature': 0.2,
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {
                            'type': 'video',
                            'source': {
                                'type': 'base64',
                                'media_type': media_type,
                                'data': payload,
                            },
                        },
                    ],
                }
            ],
        }

        data = await self._request_messages(body)
        raw_text = _extract_text_from_response(data)
        try:
            return parse_and_normalize_analysis(raw_text)
        except Exception as exc:
            raise ClaudeAnalysisError(f'Could not normalize Claude output: {exc}') from exc

    async def _analyze_with_keyframes(self, video_path: Path, reel_url: str) -> ClaudeAnalysisResult:
        with tempfile.TemporaryDirectory(prefix='contentgg-frames-') as tmp_dir:
            frame_dir = Path(tmp_dir)
            frame_paths = _extract_keyframes(video_path, frame_dir, max_frames=6)
            if not frame_paths:
                raise ClaudeAnalysisError('Could not extract frames for Claude fallback analysis')

            content_blocks: list[dict] = []
            content_blocks.append(
                {
                    'type': 'text',
                    'text': (
                        'Analyze these keyframes from an Instagram reel and output ONLY JSON with keys: '
                        'concept, script, requirements, virality, feasibility, recording_time.\\n\\n'
                        'Rules:\\n'
                        '- requirements must be concise comma-separated assets/needs\\n'
                        '- virality should map to High/Medium/Low\\n'
                        '- feasibility should map to Easy/Medium/Hard\\n'
                        '- recording_time should map to <5 / 5-15 / 15+\\n'
                        '- script should be practical and short for recreating video style\\n\\n'
                        f'Reel URL: {reel_url}\\n\\n'
                        'Creator style guide:\\n'
                        f'{self._style_guide_text}'
                    ),
                }
            )

            for frame in frame_paths:
                encoded = base64.b64encode(frame.read_bytes()).decode('utf-8')
                content_blocks.append(
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': 'image/jpeg',
                            'data': encoded,
                        },
                    }
                )

            body = {
                'model': self._model,
                'max_tokens': 1400,
                'temperature': 0.2,
                'messages': [{'role': 'user', 'content': content_blocks}],
            }
            data = await self._request_messages(body)
            raw_text = _extract_text_from_response(data)
            try:
                return parse_and_normalize_analysis(raw_text)
            except Exception as exc:
                raise ClaudeAnalysisError(f'Could not normalize Claude output: {exc}') from exc

    async def _request_messages(self, body: dict) -> dict:
        headers = {
            'x-api-key': self._api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post('https://api.anthropic.com/v1/messages', headers=headers, json=body)
        if response.status_code >= 400:
            raise ClaudeAnalysisError(f'Claude request failed ({response.status_code}): {response.text}')
        return response.json()


def _extract_text_from_response(payload: dict) -> str:
    blocks = payload.get('content')
    if not isinstance(blocks, list):
        raise ClaudeAnalysisError('Claude response missing content blocks')

    chunks: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text' and isinstance(block.get('text'), str):
            chunks.append(block['text'])

    raw_text = '\n'.join(chunks).strip()
    if not raw_text:
        raise ClaudeAnalysisError('Claude returned empty text output')
    return raw_text


def _is_unsupported_video_input_error(message: str) -> bool:
    lowered = message.lower()
    return ('input tag' in lowered and 'video' in lowered and 'invalid_request_error' in lowered) or (
        'messages.0.content.1' in lowered and 'video' in lowered
    )


def _extract_keyframes(video_path: Path, output_dir: Path, max_frames: int = 6) -> list[Path]:
    output_pattern = output_dir / 'frame-%02d.jpg'
    cmd = [
        'ffmpeg',
        '-hide_banner',
        '-loglevel',
        'error',
        '-i',
        str(video_path),
        '-vf',
        'fps=1/2,scale=720:-1',
        '-frames:v',
        str(max_frames),
        '-y',
        str(output_pattern),
    ]
    subprocess.run(cmd, check=False)
    return sorted(output_dir.glob('frame-*.jpg'))
