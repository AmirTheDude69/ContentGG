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
        # Large videos can exceed Anthropic payload limits when sent as base64 video blocks.
        # In that case we fallback to keyframe analysis.
        if video_path.stat().st_size > 18 * 1024 * 1024:
            return await self._analyze_with_keyframes(video_path, reel_url)

        try:
            return await self._analyze_with_video_input(video_path, reel_url)
        except ClaudeAnalysisError as exc:
            # Anthropic may reject video blocks or payload size for some reels/accounts/models.
            if _is_unsupported_video_input_error(str(exc)) or _is_request_too_large_error(str(exc)):
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
            '- virality must be exactly one of: High, Mid, Low\n'
            '- feasibility must be exactly one of: Easy, Complex\n'
            '- recording_time must be exactly one of: <5, 5-10, 10-30\n'
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
            profiles = [
                {'max_frames': 6, 'fps_filter': '1/2', 'scale_width': 720},
                {'max_frames': 4, 'fps_filter': '1/3', 'scale_width': 640},
                {'max_frames': 3, 'fps_filter': '1/4', 'scale_width': 480},
                {'max_frames': 2, 'fps_filter': '1/6', 'scale_width': 360},
            ]

            last_error: Exception | None = None
            for profile in profiles:
                frame_paths = _extract_keyframes(
                    video_path,
                    frame_dir,
                    max_frames=profile['max_frames'],
                    fps_filter=profile['fps_filter'],
                    scale_width=profile['scale_width'],
                )
                if not frame_paths:
                    continue

                content_blocks: list[dict] = []
                content_blocks.append(
                    {
                        'type': 'text',
                        'text': (
                            'Analyze these keyframes from an Instagram reel and output ONLY JSON with keys: '
                            'concept, script, requirements, virality, feasibility, recording_time.\\n\\n'
                            'Rules:\\n'
                            '- requirements must be concise comma-separated assets/needs\\n'
                            '- virality must be exactly one of: High, Mid, Low\\n'
                            '- feasibility must be exactly one of: Easy, Complex\\n'
                            '- recording_time must be exactly one of: <5, 5-10, 10-30\\n'
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
                try:
                    data = await self._request_messages(body)
                except ClaudeAnalysisError as exc:
                    if _is_request_too_large_error(str(exc)):
                        last_error = exc
                        continue
                    raise

                raw_text = _extract_text_from_response(data)
                try:
                    return parse_and_normalize_analysis(raw_text)
                except Exception as exc:
                    raise ClaudeAnalysisError(f'Could not normalize Claude output: {exc}') from exc

            if last_error is not None:
                raise ClaudeAnalysisError('Claude request too large even after keyframe fallback compression') from last_error
            raise ClaudeAnalysisError('Could not extract frames for Claude fallback analysis')

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


def _is_request_too_large_error(message: str) -> bool:
    lowered = message.lower()
    return 'request_too_large' in lowered or 'payload too large' in lowered or '(413)' in lowered


def _extract_keyframes(
    video_path: Path,
    output_dir: Path,
    max_frames: int = 6,
    fps_filter: str = '1/2',
    scale_width: int = 720,
) -> list[Path]:
    for existing in output_dir.glob('frame-*.jpg'):
        existing.unlink(missing_ok=True)

    output_pattern = output_dir / 'frame-%02d.jpg'
    cmd = [
        'ffmpeg',
        '-hide_banner',
        '-loglevel',
        'error',
        '-i',
        str(video_path),
        '-vf',
        f'fps={fps_filter},scale={scale_width}:-1',
        '-q:v',
        '8',
        '-frames:v',
        str(max_frames),
        '-y',
        str(output_pattern),
    ]
    subprocess.run(cmd, check=False)
    return sorted(output_dir.glob('frame-*.jpg'))
