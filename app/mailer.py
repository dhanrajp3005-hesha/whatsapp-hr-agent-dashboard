import re
import smtplib
import socket
import ssl
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app import repository
from app.config import (
    MAIL_TEMPLATE,
    MAIL_SUBJECT,
    MAIL_DELAY,
    RESUME_BUCKET,
    DAILY_SEND_CAP,
    MAX_CONSECUTIVE_TRANSIENT_FAILURES,
)
from app.db import get_service_client
from app.logger import logger

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

_TRANSIENT_SMTP_EXCEPTIONS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    ConnectionError,
    socket.timeout,
    TimeoutError,
)


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email))


def _is_transient_smtp_failure(exc: Exception) -> bool:
    """
    Distinguishes "this one address is bad" (permanent - normal list
    decay, safe to mark Failed) from "the mail server itself is
    rejecting or unreachable" (transient - likely Gmail throttling or
    flagging the account, not a fact about this recipient). Unknown
    exception types default to transient: losing a real lead to an
    unexpected bug is worse than retrying it once more on the next run.
    """

    if isinstance(exc, _TRANSIENT_SMTP_EXCEPTIONS):
        return True
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [code for code, _ in exc.recipients.values()]
        return any(code < 500 for code in codes)
    if isinstance(exc, smtplib.SMTPResponseException):
        return exc.smtp_code < 500
    return True


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


def send_pending_emails(user_id: str, job_id: Optional[str] = None) -> dict:
    """
    Sends the resume + cover email to every 'Pending' job row for this
    user, marking each Sent/Failed in the jobs table and writing an
    activity_log entry per outcome. Requires SMTP settings and a
    resume to already be configured (see app/repository.py).

    job_id, when passed (only by the send_pending_mail worker_jobs path -
    see worker/run_worker.py), is polled once per email so a user's
    "Stop sending" click (app/repository.py's request_worker_job_cancel)
    can interrupt an in-progress batch after the current email finishes.
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

    # The daily cap applies only to the uploaded-sheet pipeline -
    # WhatsApp-scanned leads are sent uncapped, per the user's request
    # that the sheet upload feature not throttle WhatsApp scanning.
    pending = repository.list_pending_job_emails(user_id, source="whatsapp")
    upload_start_index = len(pending)

    upload_paused = settings.get("upload_sending_paused", False)
    if upload_paused:
        logger.info("send_pending_emails: uploaded-sheet sending is paused for user %s", user_id)
    else:
        already_sent_today = repository.count_sent_today(user_id, source="upload")
        remaining_upload_budget = DAILY_SEND_CAP - already_sent_today
        if remaining_upload_budget > 0:
            pending += repository.list_pending_job_emails(
                user_id, source="upload", limit=remaining_upload_budget
            )
        elif repository.list_pending_job_emails(user_id, source="upload", limit=1):
            logger.info(
                "send_pending_emails: upload daily cap (%s) already reached for user %s",
                DAILY_SEND_CAP, user_id,
            )
            repository.log_activity(
                user_id, "send_capped",
                f"Daily send limit of {DAILY_SEND_CAP} for uploaded-sheet emails already reached today.",
            )

    if not pending:
        logger.info("send_pending_emails: nothing pending for user %s", user_id)
        return {"success": 0, "failed": 0}

    resume_bytes = _download_resume(resume_path)
    resume_filename = resume_path.rsplit("/", 1)[-1]
    subject, body_text, body_subtype = _resolve_mail_content(settings)

    context = ssl.create_default_context()
    success = 0
    failed = 0
    consecutive_transient_failures = 0

    smtp = smtplib.SMTP(smtp_settings["smtp_host"], smtp_settings["smtp_port"], timeout=30)
    try:
        smtp.starttls(context=context)
        smtp.login(smtp_settings["smtp_username"], smtp_settings["smtp_password"])

        cancelled = False
        for index, job in enumerate(pending):
            if job_id and repository.is_job_cancelled(job_id):
                cancelled = True
                logger.info(
                    "send_pending_emails: cancelled for user %s after %s of %s",
                    user_id, index, len(pending),
                )
                repository.log_activity(
                    user_id, "send_cancelled",
                    f"Stopped after {success} sent - {len(pending) - index} email(s) left pending.",
                )
                break

            # Re-check the live pause flag once we reach the uploaded-sheet
            # portion of this batch, so a "Stop sending" click can interrupt
            # a batch already in flight - including one started inline by
            # scanner.py after a WhatsApp scan, which has no job_id/
            # cancel_requested to poll. WhatsApp-sourced rows (earlier in
            # `pending`) are never subject to this check - they stay uncapped.
            if index >= upload_start_index and repository.is_upload_sending_paused(user_id):
                cancelled = True
                logger.info(
                    "send_pending_emails: upload sending paused mid-batch for user %s after %s of %s",
                    user_id, index, len(pending),
                )
                repository.log_activity(
                    user_id, "send_cancelled",
                    f"Uploaded-sheet sending stopped - {success} sent this batch, "
                    f"{len(pending) - index} email(s) left pending.",
                )
                break

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
                consecutive_transient_failures = 0
                logger.info("Sent to %s (user %s)", email, user_id)

                time.sleep(MAIL_DELAY)

            except Exception as exc:
                failed += 1

                if _is_transient_smtp_failure(exc):
                    # Left as Pending (not marked Failed) - the mail server
                    # itself is the problem, not this address, so it's
                    # worth retrying on the next run rather than discarding
                    # a real lead.
                    consecutive_transient_failures += 1
                    logger.exception(
                        "Transient failure sending to %s (user %s) - left pending for retry (%s consecutive)",
                        email, user_id, consecutive_transient_failures,
                    )
                else:
                    repository.mark_job_failed(user_id, job["id"])
                    repository.log_activity(user_id, "email_failed", email)
                    consecutive_transient_failures = 0
                    logger.exception("Permanently failed to send to %s (user %s)", email, user_id)

                if consecutive_transient_failures >= MAX_CONSECUTIVE_TRANSIENT_FAILURES:
                    cancelled = True
                    logger.error(
                        "send_pending_emails: %s consecutive transient failures - stopping early "
                        "for user %s (likely SMTP throttling, not bad addresses)",
                        consecutive_transient_failures, user_id,
                    )
                    repository.log_activity(
                        user_id, "error",
                        f"Stopped sending after {consecutive_transient_failures} consecutive SMTP "
                        f"failures in a row - possible throttling or account issue, not bad addresses. "
                        f"{success} sent this batch, {len(pending) - index - 1} email(s) left pending.",
                    )
                    break
    finally:
        smtp.quit()

    logger.info("send_pending_emails done for %s: success=%s failed=%s", user_id, success, failed)
    return {"success": success, "failed": failed, "cancelled": cancelled}
