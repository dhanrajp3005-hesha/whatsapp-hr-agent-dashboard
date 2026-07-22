"""
Per-user WhatsApp Web session lifecycle: QR login, connection polling,
community discovery, and disconnect. Runs only inside the worker process
(worker/run_worker.py) - never in the Vercel-deployed dashboard, since it
needs a real Playwright browser and a persistent per-user profile
directory on disk (see README "Deployment").

The dashboard talks to this indirectly: it inserts a 'whatsapp_connect'
or 'whatsapp_disconnect' row into worker_jobs (via app.repository) and
polls user_settings.whatsapp_session_status / whatsapp_qr_image, which
this module updates as it runs.
"""

import base64
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from app import repository
from app.config import BROWSER_DATA_DIR, BROWSER_USER_AGENT, HEADLESS, WHATSAPP_URL
from app.logger import logger
from app.search import list_communities

CONNECT_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 2


def _browser_data_dir(user_id: str) -> Path:
    return BROWSER_DATA_DIR / user_id


def _screenshot_qr(page) -> str | None:
    for selector in ("div[data-testid='qrcode'] canvas", "canvas"):
        locator = page.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            png_bytes = locator.screenshot(timeout=2000)
            return base64.b64encode(png_bytes).decode()
        except Exception:
            continue
    return None


def _chat_list_ready(page) -> bool:
    try:
        return page.get_by_role("textbox", name="Search or start a new chat").count() > 0
    except Exception:
        return False


def start_login_session(user_id: str) -> None:
    """
    Worker-side handler for a 'whatsapp_connect' job. Opens (or resumes)
    the user's persistent browser profile, streams QR screenshots into
    user_settings.whatsapp_qr_image until the user scans it on their
    phone, then marks the session connected and discovers their
    communities/groups.
    """

    browser_data_dir = _browser_data_dir(user_id)
    browser_data_dir.mkdir(parents=True, exist_ok=True)

    repository.set_whatsapp_status(user_id, "pending_qr", session_path=str(browser_data_dir))

    logger.info("Starting WhatsApp login session for user %s", user_id)

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(browser_data_dir),
            headless=HEADLESS,
            user_agent=BROWSER_USER_AGENT,
        )
        page = browser.new_page()

        try:
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded")

            deadline = time.time() + CONNECT_TIMEOUT_SECONDS
            connected = False

            while time.time() < deadline:
                if _chat_list_ready(page):
                    connected = True
                    break

                qr_b64 = _screenshot_qr(page)
                if qr_b64:
                    repository.set_qr_image(user_id, qr_b64)

                time.sleep(POLL_INTERVAL_SECONDS)

            if not connected:
                logger.warning("WhatsApp login timed out for user %s", user_id)
                repository.set_whatsapp_status(user_id, "expired")
                repository.set_qr_image(user_id, None)
                repository.log_activity(user_id, "error", "WhatsApp QR login timed out.")
                return

            logger.info("WhatsApp connected for user %s", user_id)
            repository.set_qr_image(user_id, None)
            repository.set_whatsapp_status(user_id, "connected", session_path=str(browser_data_dir))
            repository.log_activity(user_id, "whatsapp_connected", "")

            page.wait_for_timeout(2000)
            communities = list_communities(page)
            repository.replace_discovered_communities(user_id, communities)

        finally:
            browser.close()


def disconnect_session(user_id: str) -> None:
    """
    Worker-side handler for a 'whatsapp_disconnect' job. Wipes the
    user's persisted browser profile (equivalent to logging out on
    their phone) and resets connection status.
    """

    logger.info("Disconnecting WhatsApp session for user %s", user_id)

    browser_data_dir = _browser_data_dir(user_id)
    shutil.rmtree(browser_data_dir, ignore_errors=True)

    repository.set_whatsapp_status(user_id, "disconnected", session_path=None)
    repository.set_qr_image(user_id, None)
    repository.log_activity(user_id, "whatsapp_disconnected", "")


def get_session_status(user_id: str) -> str:
    settings = repository.get_user_settings(user_id) or {}
    return settings.get("whatsapp_session_status", "disconnected")
