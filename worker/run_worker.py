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
from app.scanner import scan_whatsapp
from app.whatsapp_session import start_login_session, disconnect_session


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


def process_job(job: dict) -> None:
    handler = JOB_HANDLERS.get(job["kind"])

    if not handler:
        repository.complete_worker_job(job["id"], "failed", f"Unknown job kind: {job['kind']}")
        return

    logger.info("Processing worker_job %s (%s) for user %s", job["id"], job["kind"], job["user_id"])

    try:
        handler(job["user_id"])
        repository.complete_worker_job(job["id"], "completed")
        logger.info("Completed worker_job %s", job["id"])
    except Exception as exc:
        logger.exception("worker_job %s failed", job["id"])
        repository.complete_worker_job(job["id"], "failed", str(exc))
        repository.log_activity(job["user_id"], "error", f"{job['kind']} failed: {exc}")


def main() -> None:
    logger.info("Worker started. Polling every %ss.", WORKER_POLL_INTERVAL_SECONDS)

    while True:
        job = repository.claim_next_worker_job()

        if job:
            process_job(job)
        else:
            time.sleep(WORKER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
