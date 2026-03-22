create extension if not exists pgcrypto;

create table if not exists saved_reels (
  id uuid primary key default gen_random_uuid(),
  reel_url text not null unique,
  source_mode text not null default 'saved_folder',
  status text not null default 'discovered',
  sheet_row integer,
  first_seen_at timestamptz not null default now(),
  last_processed_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  reel_url text not null,
  trigger_source text not null,
  status text not null default 'pending',
  attempts integer not null default 0,
  max_attempts integer not null default 3,
  payload jsonb not null default '{}'::jsonb,
  last_error text,
  next_attempt_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists jobs_active_url_idx
  on jobs(reel_url)
  where status in ('pending', 'processing');

create table if not exists bot_chats (
  chat_id bigint primary key,
  user_id bigint,
  username text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists poll_runs (
  id bigserial primary key,
  trigger_source text not null,
  status text not null,
  fetched_count integer not null default 0,
  considered_count integer not null default 0,
  enqueued_count integer not null default 0,
  error text,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);
