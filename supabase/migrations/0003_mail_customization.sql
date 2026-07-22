-- ==========================================================
-- Per-user custom email subject/body. Null means "use the app default"
-- (app.config.MAIL_SUBJECT and templates/mail.html) - see app/mailer.py.
-- ==========================================================

alter table public.user_settings
  add column mail_subject text,
  add column mail_body text;
