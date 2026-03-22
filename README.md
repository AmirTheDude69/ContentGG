# ContentGG

Automation service for this workflow:

1. Poll Instagram saved folder (`Content GG`) every 12 hours.
2. Queue unseen Reel URLs in Postgres-backed jobs.
3. Download each Reel video with yt-dlp (Just-Fetch-style downloader internals).
4. Send raw video + creator style guide to Claude Sonnet.
5. Normalize output to strict enums and upsert Google Sheet row by Link.
6. Notify Telegram DM on success and on every failure.

## Stack

- FastAPI webhook + internal API
- APScheduler interval poller
- Postgres queue/state tables (`jobs`, `saved_reels`, `poll_runs`, `bot_chats`)
- Telegram Bot API
- Anthropic Claude API
- Google Sheets API (Service Account)

## Commands (Telegram)

- `/start` register this chat for notifications
- `/add <instagram_reel_url>` enqueue manual URL
- `/status` queue and latest poll status
- `/last` last 5 jobs
- `/reprocess <row_or_url>` requeue from sheet row or direct link

## Endpoints

- `GET /healthz`
- `POST /telegram/webhook/{TELEGRAM_WEBHOOK_SECRET}`
- `POST /internal/poll` with header `x-internal-secret: INTERNAL_API_SECRET`

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill secrets in .env
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

## Railway deploy

```bash
railway login
railway init
railway add --database postgres
railway up
```

Then set all environment variables from `.env.example` in Railway.

## Notes

- `INSTAGRAM_SESSION_COOKIE` must be a valid cookie header string from a logged-in Instagram browser session.
- If Claude rejects raw video input for your account/model, jobs will fail and notify Telegram with the API error.
- Sheet mapping is fixed to columns A-I:
  - A Data Added
  - B Concept
  - C Script
  - D Requirements
  - E Virality
  - F Feasibility
  - G Recording Time
  - H Status
  - I Link
