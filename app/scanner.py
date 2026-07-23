from pathlib import Path

from playwright.sync_api import sync_playwright

from app import repository
from app.validator import validate
from app.waiter import wait_for_whatsapp
from app.search import open_community
from app.scroll_controller import collect_messages
from app.parser import extract_jobs
from app.mailer import send_pending_emails
from app.retry import retry
from app.logger import logger
from app.state import calculate_hash
from app.config import MAX_RETRY, RETRY_DELAY, HEADLESS, WHATSAPP_URL, BROWSER_USER_AGENT


def scan_whatsapp(user_id: str, community_name: str, browser_data_dir: Path) -> list[dict]:
    """
    Runs one full scan cycle for a single user: opens their persisted
    WhatsApp Web session, opens their selected community, collects any
    messages since their last checkpoint, extracts emails, saves new
    job rows, sends pending resume emails, and advances the checkpoint.

    Must only be called from the worker process (see worker/run_worker.py)
    - it launches a real Playwright browser against a persistent,
    per-user profile directory, which is not available on Vercel.
    """

    logger.info("=" * 80)
    logger.info("Starting WhatsApp Scan for user %s", user_id)
    logger.info("=" * 80)

    smtp_settings = repository.get_decrypted_smtp_settings(user_id)

    if not validate(
        browser_data_dir,
        smtp_host=smtp_settings["smtp_host"] if smtp_settings else None,
        smtp_port=smtp_settings["smtp_port"] if smtp_settings else None,
    ):
        logger.error("Validation failed for user %s.", user_id)
        repository.log_activity(user_id, "scan_failed", "Pre-flight validation failed.")
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(browser_data_dir),
            headless=HEADLESS,
            user_agent=BROWSER_USER_AGENT,
        )

        page = browser.new_page()

        try:
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded")

            retry(wait_for_whatsapp, page, retries=MAX_RETRY, delay=RETRY_DELAY)
            retry(open_community, page, community_name, retries=MAX_RETRY, delay=RETRY_DELAY)

            logger.info("Waiting for WhatsApp chat...")
            page.wait_for_timeout(4000)

            checkpoint = repository.get_checkpoint(user_id)
            last_hash = (checkpoint or {}).get("last_message_hash") or ""

            if last_hash:
                logger.info("Last Hash Loaded : %s...", last_hash[:12])
            else:
                logger.info("No previous checkpoint found.")

            messages, checkpoint_was_found = collect_messages(page, last_hash)
            logger.info("Messages Read : %s", len(messages))

            if checkpoint_was_found:
                new_messages = []
                found = last_hash == ""

                for message in messages:
                    current_hash = calculate_hash(message)

                    if found:
                        new_messages.append(message)
                    elif current_hash == last_hash:
                        found = True
            else:
                # Checkpoint genuinely couldn't be located (a very
                # high-volume chat outpacing MAX_SCROLLS, or the scroll
                # stalled before reaching it) - silently treating this
                # as "zero new messages" would drop real content.
                # Process everything collected instead; insert_jobs'
                # unique (user_id, email) constraint makes
                # re-processing an already-seen email a safe no-op.
                logger.warning(
                    "Checkpoint not found for user %s - falling back to "
                    "processing all %s collected messages.",
                    user_id, len(messages),
                )
                new_messages = messages

            logger.info("New Messages : %s", len(new_messages))

            if not new_messages:
                logger.info("No new WhatsApp messages for user %s.", user_id)
                repository.log_activity(user_id, "scan_completed", "No new messages.")
                return []

            jobs = extract_jobs(new_messages)
            logger.info("Emails Found : %s", len(jobs))

            inserted = repository.insert_jobs(user_id, jobs)
            logger.info("New Job Rows Inserted : %s", inserted)

            send_pending_emails(user_id)

            repository.save_checkpoint(user_id, calculate_hash(new_messages[-1]))
            logger.info("Checkpoint saved for user %s.", user_id)

            repository.log_activity(
                user_id, "scan_completed", f"{len(jobs)} email(s) found, {inserted} new."
            )

            logger.info("=" * 80)
            logger.info("Scan Completed for user %s", user_id)
            logger.info("=" * 80)

            return jobs

        finally:
            browser.close()
