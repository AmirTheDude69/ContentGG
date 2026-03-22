from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = Field(default='development', alias='APP_ENV')
    app_base_url: str = Field(default='', alias='APP_BASE_URL')
    port: int = Field(default=8000, alias='PORT')
    timezone: str = Field(default='Asia/Bangkok', alias='TIMEZONE')

    database_url: str = Field(alias='DATABASE_URL')

    telegram_bot_token: str = Field(alias='TELEGRAM_BOT_TOKEN')
    telegram_webhook_secret: str = Field(alias='TELEGRAM_WEBHOOK_SECRET')
    internal_api_secret: str = Field(alias='INTERNAL_API_SECRET')

    instagram_saved_folder_url: str = Field(alias='INSTAGRAM_SAVED_FOLDER_URL')
    instagram_session_cookie: str = Field(default='', alias='INSTAGRAM_SESSION_COOKIE')

    anthropic_api_key: str = Field(alias='ANTHROPIC_API_KEY')
    anthropic_model: str = Field(default='claude-sonnet-4-20250514', alias='ANTHROPIC_MODEL')

    google_service_account_json: str = Field(alias='GOOGLE_SERVICE_ACCOUNT_JSON')
    google_sheet_id: str = Field(alias='GOOGLE_SHEET_ID')
    google_sheet_worksheet: str = Field(default='Sheet1', alias='GOOGLE_SHEET_WORKSHEET')

    poll_interval_hours: int = Field(default=12, alias='POLL_INTERVAL_HOURS')
    poll_backfill_limit: int = Field(default=20, alias='POLL_BACKFILL_LIMIT')
    retry_max_attempts: int = Field(default=3, alias='RETRY_MAX_ATTEMPTS')

    style_guide_path: str = Field(default='./CLAUDE_STYLE_GUIDE.md', alias='STYLE_GUIDE_PATH')

    @model_validator(mode='after')
    def _validate_required(self) -> 'Settings':
        required = {
            'DATABASE_URL': self.database_url,
            'TELEGRAM_BOT_TOKEN': self.telegram_bot_token,
            'TELEGRAM_WEBHOOK_SECRET': self.telegram_webhook_secret,
            'INTERNAL_API_SECRET': self.internal_api_secret,
            'ANTHROPIC_API_KEY': self.anthropic_api_key,
            'GOOGLE_SERVICE_ACCOUNT_JSON': self.google_service_account_json,
            'GOOGLE_SHEET_ID': self.google_sheet_id,
            'INSTAGRAM_SAVED_FOLDER_URL': self.instagram_saved_folder_url,
        }
        missing = [key for key, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f'Missing required environment variables: {", ".join(missing)}')
        return self

    @property
    def webhook_path(self) -> str:
        return f'/telegram/webhook/{self.telegram_webhook_secret}'

    @property
    def webhook_url(self) -> str:
        return f"{self.app_base_url.rstrip('/')}{self.webhook_path}"

    @property
    def style_guide_file(self) -> Path:
        return Path(self.style_guide_path)

    @property
    def google_service_account_info(self) -> dict[str, Any]:
        raw = self.google_service_account_json.strip()
        if raw.startswith('{'):
            return json.loads(raw)
        return json.loads(Path(raw).read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
