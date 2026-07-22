-- ==========================================================
-- whatsapp-hr-agent-dashboard: initial schema
-- Multi-tenant tables, one row/set of rows per Supabase Auth user.
-- auth.users is managed by Supabase Auth itself - not recreated here.
-- ==========================================================

create extension if not exists pgcrypto;

-- ----------------------------------------------------------
-- user_settings: per-user app profile / settings
-- ----------------------------------------------------------
create table public.user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  smtp_host text,
  smtp_port int,
  smtp_username text,
  smtp_password_encrypted text,        -- Fernet ciphertext, never plaintext
  from_email text,
  resume_storage_path text,            -- path within the "resumes" storage bucket
  whatsapp_session_status text default 'disconnected'
    check (whatsapp_session_status in ('disconnected', 'pending_qr', 'connected', 'expired')),
  whatsapp_session_path text,          -- browser_data/{user_id} on the worker host
  whatsapp_qr_image text,              -- latest QR screenshot, base64-encoded PNG; worker
                                        -- writes it every ~2s while pending_qr, dashboard
                                        -- polls it - lets a stateless Vercel function show
                                        -- a live QR without ever touching Playwright itself
  selected_community_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.user_settings enable row level security;

create policy "Users manage their own settings"
  on public.user_settings for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ----------------------------------------------------------
-- whatsapp_communities: communities/groups discovered per user
-- ----------------------------------------------------------
create table public.whatsapp_communities (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  community_name text not null,
  discovered_at timestamptz not null default now(),
  unique (user_id, community_name)
);

alter table public.whatsapp_communities enable row level security;

create policy "Users manage their own communities"
  on public.whatsapp_communities for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ----------------------------------------------------------
-- jobs: extracted job/email rows per user (replaces output/jobs.xlsx)
-- ----------------------------------------------------------
create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  company text,
  job_title text,
  email text not null,
  location text,
  experience text,
  apply_link text,
  mail_status text not null default 'Pending'
    check (mail_status in ('Pending', 'Sent', 'Failed')),
  source_message_hash text,
  created_at timestamptz not null default now(),
  sent_at timestamptz
);

create unique index jobs_user_email_unique on public.jobs (user_id, email);
create index jobs_user_status_idx on public.jobs (user_id, mail_status);

alter table public.jobs enable row level security;

create policy "Users manage their own jobs"
  on public.jobs for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ----------------------------------------------------------
-- scan_checkpoints: last-scanned position per user (replaces checkpoint.json)
-- ----------------------------------------------------------
create table public.scan_checkpoints (
  user_id uuid primary key references auth.users(id) on delete cascade,
  last_header text,
  last_email text,
  last_message_hash text,
  updated_at timestamptz not null default now()
);

alter table public.scan_checkpoints enable row level security;

create policy "Users manage their own checkpoint"
  on public.scan_checkpoints for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ----------------------------------------------------------
-- activity_log: dashboard activity feed
-- ----------------------------------------------------------
create table public.activity_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event_type text not null
    check (event_type in (
      'scan_requested', 'scan_started', 'scan_completed', 'scan_failed',
      'email_sent', 'email_failed', 'whatsapp_connected', 'whatsapp_disconnected', 'error'
    )),
  message text,
  created_at timestamptz not null default now()
);

create index activity_log_user_created_idx on public.activity_log (user_id, created_at desc);

alter table public.activity_log enable row level security;

create policy "Users manage their own activity log"
  on public.activity_log for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ----------------------------------------------------------
-- worker_jobs: generic queue table bridging the Vercel dashboard (which
-- cannot run Playwright at all - no scan, no QR login, no disconnect)
-- and the always-on worker process (see README "Deployment"). The
-- dashboard's POST /api/scan, /api/whatsapp/connect and
-- /api/whatsapp/disconnect each insert a 'pending' row with the
-- relevant `kind`; the worker polls for pending rows, claims one, and
-- updates its status as it progresses.
-- ----------------------------------------------------------
create table public.worker_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null
    check (kind in ('scan', 'whatsapp_connect', 'whatsapp_disconnect')),
  status text not null default 'pending'
    check (status in ('pending', 'running', 'completed', 'failed')),
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  error_message text
);

create index worker_jobs_status_idx on public.worker_jobs (status, requested_at);
create index worker_jobs_user_kind_idx on public.worker_jobs (user_id, kind, status);

alter table public.worker_jobs enable row level security;

create policy "Users manage their own worker jobs"
  on public.worker_jobs for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- The worker authenticates with the service-role key, which bypasses RLS
-- entirely (by design, per Supabase semantics) - no separate worker policy
-- is required for it to read/claim rows across all users.

-- ----------------------------------------------------------
-- updated_at maintenance trigger, reused across tables that have the column
-- ----------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger user_settings_set_updated_at
  before update on public.user_settings
  for each row execute function public.set_updated_at();

create trigger scan_checkpoints_set_updated_at
  before update on public.scan_checkpoints
  for each row execute function public.set_updated_at();
