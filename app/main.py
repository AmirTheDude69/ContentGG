from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request

from app import db
from app.bot.commands import extract_reel_url, parse_bot_command
from app.config import Settings, get_settings
from app.poller import SavedFolderPoller
from app.repositories import (
    add_or_update_chat,
    enqueue_job,
    last_poll_summary,
    list_active_chats,
    list_recent_jobs,
    queue_stats,
)
from app.services.claude import ClaudeClient
from app.services.downloader import ReelDownloader
from app.services.instagram import InstagramSavedFolderClient
from app.services.processor import PipelineProcessor, ProcessorConfig
from app.services.sheets import SheetsClient
from app.services.telegram import TelegramClient
from app.worker import JobWorker

LOGGER = logging.getLogger(__name__)


@dataclass
class AppServices:
    settings: Settings
    telegram: TelegramClient
    sheets: SheetsClient
    poller: SavedFolderPoller
    worker: JobWorker
    scheduler: AsyncIOScheduler


def _load_style_guide(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f'Style guide file not found: {path}')
    return path.read_text(encoding='utf-8')


async def _run_scheduled_poll(services: AppServices) -> None:
    try:
        result = await services.poller.run_once('scheduled')
        if result.enqueued_count > 0:
            chats = await list_active_chats()
            if chats:
                await services.telegram.broadcast(
                    chats,
                    (
                        'ContentGG scheduled poll completed.\n'
                        f'- Fetched: {result.fetched_count}\n'
                        f'- Considered: {result.considered_count}\n'
                        f'- Enqueued: {result.enqueued_count}'
                    ),
                )
    except Exception as exc:
        LOGGER.exception('Scheduled poll failed')
        chats = await list_active_chats()
        if chats:
            await services.telegram.broadcast(chats, f'ContentGG poll failed: {str(exc)[:300]}')


async def _send_message(services: AppServices, chat_id: int, text: str) -> None:
    await services.telegram.send_message(chat_id, text)


async def _handle_start(services: AppServices, message: dict[str, Any]) -> None:
    chat = message.get('chat') or {}
    from_user = message.get('from') or {}
    chat_id = int(chat.get('id'))
    user_id = int(from_user.get('id')) if from_user.get('id') is not None else None
    username = from_user.get('username')

    await add_or_update_chat(chat_id=chat_id, user_id=user_id, username=username)

    await _send_message(
        services,
        chat_id,
        (
            'ContentGG is connected.\n\n'
            'Commands:\n'
            '/add <instagram_reel_url>\n'
            '/status\n'
            '/last\n'
            '/reprocess <row_or_url>'
        ),
    )


async def _handle_add(services: AppServices, message: dict[str, Any], argument: str) -> None:
    chat_id = int((message.get('chat') or {}).get('id'))
    reel_url = extract_reel_url(argument)
    if not reel_url:
        await _send_message(services, chat_id, 'Please provide a valid Instagram reel URL.')
        return

    inserted = await enqueue_job(
        reel_url=reel_url,
        trigger_source='manual_add',
        max_attempts=services.settings.retry_max_attempts,
    )
    if inserted:
        await _send_message(services, chat_id, f'Queued for processing: {reel_url}')
    else:
        await _send_message(services, chat_id, 'That reel is already queued or processing.')


async def _handle_status(services: AppServices, message: dict[str, Any]) -> None:
    chat_id = int((message.get('chat') or {}).get('id'))
    stats = await queue_stats()
    poll = await last_poll_summary()
    poll_line = 'No poll has run yet.'
    if poll:
        poll_line = (
            f"Last poll [{poll['status']}]: fetched={poll['fetched_count']} considered={poll['considered_count']} enqueued={poll['enqueued_count']}"
        )
        if poll.get('error'):
            poll_line += f" | error={poll['error'][:120]}"

    await _send_message(
        services,
        chat_id,
        (
            'ContentGG status\n'
            f"- Pending: {stats.get('pending', 0)}\n"
            f"- Processing: {stats.get('processing', 0)}\n"
            f"- Completed: {stats.get('completed', 0)}\n"
            f"- Failed: {stats.get('failed', 0)}\n"
            f'- {poll_line}'
        ),
    )


async def _handle_last(services: AppServices, message: dict[str, Any]) -> None:
    chat_id = int((message.get('chat') or {}).get('id'))
    jobs = await list_recent_jobs(limit=5)
    if not jobs:
        await _send_message(services, chat_id, 'No jobs yet.')
        return

    lines = ['Recent jobs:']
    for job in jobs:
        lines.append(f"- {job['status']} ({job['trigger_source']}) {job['reel_url']}")
    await _send_message(services, chat_id, '\n'.join(lines))


async def _handle_reprocess(services: AppServices, message: dict[str, Any], argument: str) -> None:
    chat_id = int((message.get('chat') or {}).get('id'))
    argument = argument.strip()
    if not argument:
        await _send_message(services, chat_id, 'Usage: /reprocess <row_or_url>')
        return

    reel_url: str | None
    if argument.isdigit():
        reel_url = await services.sheets.get_link_by_row(int(argument))
        if not reel_url:
            await _send_message(services, chat_id, f'No link found in sheet row {argument}.')
            return
    else:
        reel_url = extract_reel_url(argument)
        if not reel_url:
            await _send_message(services, chat_id, 'Please provide a valid row number or Instagram reel URL.')
            return

    inserted = await enqueue_job(
        reel_url=reel_url,
        trigger_source='reprocess',
        max_attempts=services.settings.retry_max_attempts,
        payload={'force': True},
    )
    if inserted:
        await _send_message(services, chat_id, f'Reprocess queued: {reel_url}')
    else:
        await _send_message(services, chat_id, 'That reel is already queued or processing.')


async def handle_telegram_update(services: AppServices, payload: dict[str, Any]) -> None:
    message = payload.get('message')
    if not isinstance(message, dict):
        return

    text = str(message.get('text') or '').strip()
    if not text:
        return

    command = parse_bot_command(text)
    if command.name == '/start':
        await _handle_start(services, message)
    elif command.name == '/add':
        await _handle_add(services, message, command.argument)
    elif command.name == '/status':
        await _handle_status(services, message)
    elif command.name == '/last':
        await _handle_last(services, message)
    elif command.name == '/reprocess':
        await _handle_reprocess(services, message, command.argument)
    else:
        chat_id = int((message.get('chat') or {}).get('id'))
        maybe_url = extract_reel_url(text)
        if maybe_url:
            await _handle_add(services, message, maybe_url)
        else:
            await _send_message(services, chat_id, 'Unknown command. Use /start for available commands.')


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    settings = get_settings()

    style_guide_text = _load_style_guide(settings.style_guide_file)

    telegram = TelegramClient(settings.telegram_bot_token)
    sheets = SheetsClient(
        service_account_info=settings.google_service_account_info,
        sheet_id=settings.google_sheet_id,
        worksheet_name=settings.google_sheet_worksheet,
    )
    instagram = InstagramSavedFolderClient(settings.instagram_session_cookie)
    poller = SavedFolderPoller(settings=settings, instagram_client=instagram)

    processor = PipelineProcessor(
        downloader=ReelDownloader(),
        claude=ClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            style_guide_text=style_guide_text,
        ),
        sheets=sheets,
        config=ProcessorConfig(
            timezone=settings.timezone,
            instagram_session_cookie=settings.instagram_session_cookie,
        ),
    )

    worker = JobWorker(processor=processor, telegram=telegram)
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    services = AppServices(
        settings=settings,
        telegram=telegram,
        sheets=sheets,
        poller=poller,
        worker=worker,
        scheduler=scheduler,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await db.connect_db()
        await db.init_schema()

        if settings.app_base_url.strip():
            await telegram.set_webhook(settings.webhook_url)
        else:
            LOGGER.warning('APP_BASE_URL not configured; Telegram webhook registration skipped')

        worker.start()

        scheduler.add_job(
            _run_scheduled_poll,
            trigger='interval',
            hours=settings.poll_interval_hours,
            kwargs={'services': services},
            id='saved-folder-poll',
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        scheduler.start()

        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            await worker.stop()
            await db.close_db()

    app = FastAPI(title='ContentGG', lifespan=lifespan)
    app.state.services = services

    @app.get('/healthz')
    async def healthz() -> dict[str, str]:
        return {'status': 'ok'}

    @app.post('/telegram/webhook/{secret}')
    async def telegram_webhook(secret: str, request: Request) -> dict[str, bool]:
        if secret != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail='Invalid webhook secret')

        payload = await request.json()
        await handle_telegram_update(services, payload)
        return {'ok': True}

    @app.post('/internal/poll')
    async def internal_poll(request: Request) -> dict[str, Any]:
        provided_secret = request.headers.get('x-internal-secret', '')
        if provided_secret != settings.internal_api_secret:
            raise HTTPException(status_code=403, detail='Invalid internal secret')

        result = await poller.run_once('internal_api')
        return {
            'status': 'ok',
            'fetched_count': result.fetched_count,
            'considered_count': result.considered_count,
            'enqueued_count': result.enqueued_count,
            'completed_at': result.completed_at.isoformat(),
        }

    return app


app = create_app()
