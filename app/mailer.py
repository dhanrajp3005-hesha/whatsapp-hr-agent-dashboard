import re
import smtplib
import ssl
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app import repository
from app.config import MAIL_TEMPLATE, MAIL_SUBJECT, MAIL_DELAY, RESUME_BUCKET, DAILY_SEND_CAP
from app.db import get_service_client
from app.logger import logger

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email))


def _download_resume(resume_storage_path: str) -> bytes:
    return get_service_client().storage.from_(RESUME_BUCKET).download(resume_storage_path)


def _resolve_mail_content(settings: dict) -> tuple[str, str, str]:
    """
    Returns (subject, body_text, body_subtype). A user's custom
    mail_subject/mail_body (set via /api/settings/mail-content) override
    the app defaults (MAIL_SUBJECT, templates/mail.html) when present.
    A custom body is sent as HTML if it contains a tag, otherwise as
    plain text - so users don't have to write HTML by hand.
    """

    subject = settings.get("mail_subject") or MAIL_SUBJECT
    custom_body = settings.get("mail_body")

    if custom_body:
        subtype = "html" if "<" in custom_body and ">" in custom_body else "plain"
        return subject, custom_body, subtype

    return subject, MAIL_TEMPLATE.read_text(encoding="utf-8"), "html"


def send_test_email(user_id: str, smtp_settings: dict) -> None:
    """
    Sends a single plain-text test email to the user's own from_email,
    used by the onboarding/settings "Send test email" button. Raises on
    any failure so the caller can surface it to the user.
    """

    message = MIMEMultipart()
    message["From"] = smtp_settings["from_email"]
    message["To"] = smtp_settings["from_email"]
    message["Subject"] = "WhatsApp HR Agent - test email"
    message.attach(MIMEText("Your SMTP settings are working correctly.", "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_settings["smtp_host"], smtp_settings["smtp_port"], timeout=30) as smtp:
        smtp.starttls(context=context)
        smtp.login(smtp_settings["smtp_username"], smtp_settings["smtp_password"])
        smtp.sendmail(smtp_settings["from_email"], [smtp_settings["from_email"]], message.as_string())


def send_pending_emails(user_id: str) -> dict:
    """
    Sends the resume + cover email to every 'Pending' job row for this
    user, marking each Sent/Failed in the jobs table and writing an
    activity_log entry per outcome. Requires SMTP settings and a
    resume to already be configured (see app/repository.py).
    """

    smtp_settings = repository.get_decrypted_smtp_settings(user_id)
    if not smtp_settings:
        logger.warning("send_pending_emails: no SMTP settings for user %s", user_id)
        repository.log_activity(user_id, "error", "SMTP settings not configured - emails not sent.")
        return {"success": 0, "failed": 0}

    settings = repository.get_user_settings(user_id) or {}
    resume_path = settings.get("resume_storage_path")
    if not resume_path:
        logger.warning("send_pending_emails: no resume uploaded for user %s", user_id)
        repository.log_activity(user_id, "error", "Resume not uploaded - emails not sent.")
        return {"success": 0, "failed": 0}

    already_sent_today = repository.count_sent_today(user_id)
    remaining_budget = DAILY_SEND_CAP - already_sent_today
    if remaining_budget <= 0:
        logger.info(
            "send_pending_emails: daily cap (%s) already reached for user %s", DAILY_SEND_CAP, user_id
        )
        repository.log_activity(
            user_id, "send_capped", f"Daily send limit of {DAILY_SEND_CAP} already reached today."
        )
        return {"success": 0, "failed": 0, "capped": True}

    pending = repository.list_pending_job_emails(user_id, limit=remaining_budget)
    if not pending:
        logger.info("send_pending_emails: nothing pending for user %s", user_id)
        return {"success": 0, "failed": 0}

    resume_bytes = _download_resume(resume_path)
    resume_filename = resume_path.rsplit("/", 1)[-1]
    subject, body_text, body_subtype = _resolve_mail_content(settings)

    context = ssl.create_default_context()
    success = 0
    failed = 0

    smtp = smtplib.SMTP(smtp_settings["smtp_host"], smtp_settings["smtp_port"], timeout=30)
    try:
        smtp.starttls(context=context)
        smtp.login(smtp_settings["smtp_username"], smtp_settings["smtp_password"])

        for job in pending:
            email = job["email"]

            if not is_valid_email(email):
                logger.warning("Skipping invalid email: %s", email)
                continue

            try:
                message = MIMEMultipart()
                message["From"] = smtp_settings["from_email"]
                message["To"] = email
                message["Subject"] = subject
                message.attach(MIMEText(body_text, body_subtype))

                attachment = MIMEBase("application", "octet-stream")
                attachment.set_payload(resume_bytes)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    "Content-Disposition", f'attachment; filename="{resume_filename}"'
                )
                message.attach(attachment)

                smtp.sendmail(smtp_settings["from_email"], [email], message.as_string())

                repository.mark_job_sent(user_id, job["id"])
                repository.log_activity(user_id, "email_sent", email)
                success += 1
                logger.info("Sent to %s (user %s)", email, user_id)

                time.sleep(MAIL_DELAY)

            except Exception:
                repository.mark_job_failed(user_id, job["id"])
                repository.log_activity(user_id, "email_failed", email)
                failed += 1
                logger.exception("Failed to send to %s (user %s)", email, user_id)
    finally:
        smtp.quit()

    logger.info("send_pending_emails done for %s: success=%s failed=%s", user_id, success, failed)
    return {"success": success, "failed": failed}
