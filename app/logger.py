import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.config import LOG_DIR

# ==========================================================
# Log Directory
# ==========================================================

LOG_DIR.mkdir(parents=True, exist_ok=True)

APP_LOG = LOG_DIR / "app.log"
ERROR_LOG = LOG_DIR / "error.log"

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
    # Console
    # ------------------------------------------------------

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    # ------------------------------------------------------
    # App Log
    # ------------------------------------------------------

    app_handler = TimedRotatingFileHandler(
        APP_LOG,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )

    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)

    # ------------------------------------------------------
    # Error Log
    # ------------------------------------------------------

    error_handler = TimedRotatingFileHandler(
        ERROR_LOG,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )

    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    logger.addHandler(console)
    logger.addHandler(app_handler)
    logger.addHandler(error_handler)

    logger.propagate = False
