"""
Always-on worker process - the half of this project that Vercel cannot
run (see README "Deployment"). Polls Supabase's worker_jobs table for
pending scan / WhatsApp-connect / WhatsApp-disconnect jobs queued by the
dashboard, and executes them one at a time against real, persistent
Playwright browser profiles under browser_data/{user_id}.

Run with:
    python -m worker.run_worker

Requires the same .env as the dashboard (SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY, APP_ENCRYPTION_KEY, etc.) plus a machine with
disk that survives restarts and, unless WHATSAPP_HEADLESS=true, an X
display for the Playwright browser.
"""

import time

from app import repository
from app.config import BROWSER_DATA_DIR, WORKER_POLL_INTERVAL_SECONDS
from app.logger import logger
from app.mailer import send_pending_emails
from app.scanner import scan_whatsapp
from app.whatsapp_session import start_login_session, disconnect_session

STALE_RUNNING_JOB_SECONDS = 600


def _run_scan(user_id: str) -> None:
    settings = repository.get_user_settings(user_id) or {}
    community_name = settings.get("selected_community_name")

    if not community_name:
        raise RuntimeError("No community selected - finish onboarding first.")

    repository.log_activity(user_id, "scan_started", community_name)
    scan_whatsapp(user_id, community_name, BROWSER_DATA_DIR / user_id)


JOB_HANDLERS = {
    "scan": _run_scan,
    "whatsapp_connect": start_login_session,
    "whatsapp_disconnect": disconnect_session,
}


def _safe_complete_worker_job(job_id: str, status: str, error_message: str = None) -> None:
    """
    Recording a job's outcome can itself fail (e.g. a transient network
    blip affecting Supabase right when a job also failed for the same
    reason - exactly what crashed this worker once already). Never let
    that escape uncaught: the job row staying stuck in 'running' is
    recoverable (see reset_stale_running_jobs below); a dead worker
    process is not.
    """

    try:
        repository.complete_worker_job(job_id, status, error_message)
    except Exception:
        logger.exception("Could not record worker_job %s as %s - will self-heal on next startup.", job_id, status)


def _safe_log_activity(user_id: str, event_type: str, message: str) -> None:
    try:
        repository.log_activity(user_id, event_type, message)
    except Exception:
        logger.exception("Could not write activity_log entry for user %s", user_id)


def process_job(job: dict) -> None:
    handler = JOB_HANDLERS.get(job["kind"])

    if not handler:
        _safe_complete_worker_job(job["id"], "failed", f"Unknown job kind: {job['kind']}")
        return

    logger.info("Processing worker_job %s (%s) for user %s", job["id"], job["kind"], job["user_id"])

    try:
        # send_pending_mail is the one kind a user can interrupt mid-run
        # (see app/mailer.py's cancel_requested check) - it alone needs
        # its own job_id passed through so it knows which row to poll.
        if job["kind"] == "send_pending_mail":
            handler(job["user_id"], job_id=job["id"])
        else:
            handler(job["user_id"])
        _safe_complete_worker_job(job["id"], "completed")
        logger.info("Completed worker_job %s", job["id"])
    except Exception as exc:
        logger.exception("worker_job %s failed", job["id"])
        _safe_complete_worker_job(job["id"], "failed", str(exc))
        _safe_log_activity(job["user_id"], "error", f"{job['kind']} failed: {exc}")


def main() -> None:
    logger.info("Worker started. Polling every %ss.", WORKER_POLL_INTERVAL_SECONDS)

    try:
        reclaimed = repository.reset_stale_running_jobs(STALE_RUNNING_JOB_SECONDS)
        if reclaimed:
            logger.warning("Reclaimed %s job(s) stuck 'running' from a previous crash.", reclaimed)
    except Exception:
        logger.exception("Could not check for stale running jobs at startup.")

    while True:
        try:
            job = repository.claim_next_worker_job()
        except Exception:
            # A transient Supabase/network outage must never kill this
            # process - that's exactly what happened before this fix.
            logger.exception("Failed to poll worker_jobs - retrying shortly.")
            time.sleep(WORKER_POLL_INTERVAL_SECONDS)
            continue

        if job:
            process_job(job)
        else:
            time.sleep(WORKER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
