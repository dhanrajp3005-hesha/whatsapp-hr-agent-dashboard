import logging
from logging.handlers import TimedRotatingFileHandler

from app.config import LOG_DIR

# ==========================================================
# Logger
# ==========================================================

logger = logging.getLogger("whatsapp_hr_agent")

if not logger.handlers:

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )

    # ------------------------------------------------------
    # Console - always attached. This is the only handler on a
    # read-only-filesystem deployment (e.g. Vercel Functions, where
    # only /tmp is writable); Vercel already captures stdout/stderr in
    # its own Functions logs UI.
    # ------------------------------------------------------

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # ------------------------------------------------------
    # App / Error log files - best effort only. Any environment without
    # a writable LOG_DIR falls back to console-only logging instead of
    # crashing the import of this module - and therefore every module
    # that imports it, including app.api.
    # ------------------------------------------------------

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        app_handler = TimedRotatingFileHandler(
            LOG_DIR / "app.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        app_handler.setLevel(logging.INFO)
        app_handler.setFormatter(formatter)
        logger.addHandler(app_handler)

        error_handler = TimedRotatingFileHandler(
            LOG_DIR / "error.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        logger.addHandler(error_handler)

    except OSError:
        logger.warning(
            "LOG_DIR (%s) is not writable - file logging disabled, console-only.",
            LOG_DIR,
        )

    logger.propagate = False
