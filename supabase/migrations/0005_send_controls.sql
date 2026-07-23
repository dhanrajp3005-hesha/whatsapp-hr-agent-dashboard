-- ==========================================================
-- Manual stop/start control over the uploaded-sheet sending pipeline.
-- WhatsApp-scanned leads are a separate, uncapped pipeline and are
-- unaffected by either of these - see app/mailer.py's send_pending_emails.
-- ==========================================================

-- Persists across days/uploads until the user explicitly resumes -
-- checked before the upload portion of every send_pending_emails call,
-- and before auto-queueing a send job right after a new upload.
alter table public.user_settings
  add column upload_sending_paused boolean not null default false;

-- Lets a "Stop sending" click interrupt an already-running send_pending_mail
-- job mid-batch (checked once per email, between sends) rather than only
-- preventing future runs from starting.
alter table public.worker_jobs
  add column cancel_requested boolean not null default false;

alter table public.activity_log drop constraint activity_log_event_type_check;
alter table public.activity_log
  add constraint activity_log_event_type_check
  check (event_type in (
    'scan_requested', 'scan_started', 'scan_completed', 'scan_failed',
    'email_sent', 'email_failed', 'whatsapp_connected', 'whatsapp_disconnected',
    'error', 'upload_processed', 'send_capped',
    'send_paused', 'send_resumed', 'send_cancelled'
  ));
