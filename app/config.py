from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

# ==========================================================
# Project Paths
# ==========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# Per-user browser profiles live under BROWSER_DATA_DIR / {user_id}.
# This directory is only ever touched by the worker process (see
# app/whatsapp_session.py, app/scanner.py) - never by the Vercel-deployed
# dashboard, which has no persistent disk.
BROWSER_DATA_DIR = BASE_DIR / "browser_data"

LOG_DIR = BASE_DIR / "logs"
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Read-only deployment filesystem (e.g. Vercel Functions, where only
    # /tmp is writable). app/logger.py performs the same defensive check
    # before attaching file handlers and falls back to console-only.
    pass

MAIL_TEMPLATE = BASE_DIR / "templates" / "mail.html"

# ==========================================================
# Supabase
# ==========================================================
# The service role key must never be sent to the browser - it is only
# ever used server-side (app/db.py). The browser only ever sees
# SUPABASE_URL + SUPABASE_ANON_KEY, embedded in the login/signup pages.

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

RESUME_BUCKET = "resumes"

# ==========================================================
# App secrets
# ==========================================================

# Fernet key used to encrypt/decrypt each user's SMTP password at rest,
# and (see app/auth.py) to encrypt the session cookie holding their
# Supabase access/refresh tokens - same key, same property needed both
# places: opaque ciphertext at rest, not just a tamper-evident signature.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
APP_ENCRYPTION_KEY = os.getenv("APP_ENCRYPTION_KEY", "")

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days

# ==========================================================
# WhatsApp / Playwright defaults
# ==========================================================

WHATSAPP_URL = "https://web.whatsapp.com"
HEADLESS = os.getenv("WHATSAPP_HEADLESS", "true").lower() == "true"

# Playwright's headless Chromium reports "HeadlessChrome" in its user-agent,
# which WhatsApp Web specifically detects and blocks with an "update your
# browser" page - regardless of the actual engine version. Overriding the
# UA to a normal desktop Chrome string avoids that false block.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

WAIT_TIME = 30000
MAX_SCROLLS = 50
SCROLL_DELAY = 2

# ==========================================================
# Retry / mail defaults
# ==========================================================

MAX_RETRY = 3
RETRY_DELAY = 2

MAIL_SUBJECT = os.getenv(
    "MAIL_SUBJECT",
    "Application for AWS DevOps Engineer | 5 Years Experience",
)
MAIL_DELAY = int(os.getenv("MAIL_DELAY", "15"))

# ==========================================================
# Scan rate limiting (Section 4: one active scan at a time per user,
# minimum interval between manual triggers)
# ==========================================================

MIN_SCAN_INTERVAL_SECONDS = int(os.getenv("MIN_SCAN_INTERVAL_SECONDS", "300"))

# ==========================================================
# Daily send cap - applies only to the uploaded-sheet pipeline (see
# app/mailer.py's send_pending_emails); WhatsApp-scanned leads are sent
# uncapped. Also the upload endpoint's max file size (app/api.py).
# ==========================================================

DAILY_SEND_CAP = int(os.getenv("DAILY_SEND_CAP", "250"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(4 * 1024 * 1024)))

# ==========================================================
# Worker polling
# ==========================================================

WORKER_POLL_INTERVAL_SECONDS = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "10"))


def require_supabase_config() -> None:
    """
    Raise a clear error if Supabase config is missing. Called lazily by
    app/db.py the first time a client is actually needed, rather than at
    import time, so the module tree stays importable (e.g. for tooling,
    tests) without real credentials present.
    """

    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", SUPABASE_URL),
            ("SUPABASE_ANON_KEY", SUPABASE_ANON_KEY),
            ("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_SERVICE_ROLE_KEY),
        )
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required Supabase configuration: "
            f"{', '.join(missing)}. Check your .env file."
        )


def require_encryption_key() -> None:
    if not APP_ENCRYPTION_KEY:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and add it to .env."
        )
