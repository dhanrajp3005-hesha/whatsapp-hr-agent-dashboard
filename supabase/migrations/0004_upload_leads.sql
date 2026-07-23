-- ==========================================================
-- Bulk email-list upload feature: distinguish upload-sourced leads
-- from WhatsApp-scanned ones, add a worker_jobs kind for sending mail
-- with no browser involved, and new activity_log event types.
-- ==========================================================

-- Constant default is metadata-only in Postgres 11+, so this backfills
-- every existing row for free with zero change needed to app/scanner.py
-- (its insert_jobs calls keep defaulting to 'whatsapp').
alter table public.jobs
  add column source text not null default 'whatsapp'
  check (source in ('whatsapp', 'upload'));

-- Speeds up the "how many sent today" query used by the new daily cap.
create index jobs_user_sent_at_idx on public.jobs (user_id, sent_at) where mail_status = 'Sent';

-- New worker_jobs kind: sends whatever's already Pending, no browser
-- needed (used by the upload flow - see app/api.py, worker/run_worker.py).
alter table public.worker_jobs drop constraint worker_jobs_kind_check;
alter table public.worker_jobs
  add constraint worker_jobs_kind_check
  check (kind in ('scan', 'whatsapp_connect', 'whatsapp_disconnect', 'send_pending_mail'));

-- New activity_log event types: one per upload processed, one when the
-- daily send cap blocks some/all pending sends (so a user who just
-- uploaded thousands of leads understands why only some went out).
alter table public.activity_log drop constraint activity_log_event_type_check;
alter table public.activity_log
  add constraint activity_log_event_type_check
  check (event_type in (
    'scan_requested', 'scan_started', 'scan_completed', 'scan_failed',
    'email_sent', 'email_failed', 'whatsapp_connected', 'whatsapp_disconnected',
    'error', 'upload_processed', 'send_capped'
  ));
