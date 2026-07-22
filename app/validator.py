from pathlib import Path
import socket
from typing import Optional

from app.logger import logger
from app.config import MAIL_TEMPLATE, LOG_DIR


def check_file(path: Path, name: str) -> bool:
    if not path.exists():
        logger.error("%s not found : %s", name, path)
        return False

    logger.info("%s OK : %s", name, path)
    return True


def check_directory(path: Path, name: str) -> bool:
    if not path.exists():
        logger.warning("%s not found. Creating...", name)

        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.info("%s created.", name)
        except Exception:
            logger.exception("Unable to create %s", name)
            return False

    logger.info("%s OK : %s", name, path)
    return True


def check_internet() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=5)
        logger.info("Internet connectivity OK")
        return True
    except Exception:
        logger.exception("Internet connectivity failed")
        return False


def check_smtp(smtp_host: str, smtp_port: int) -> bool:
    try:
        socket.create_connection((smtp_host, smtp_port), timeout=5)
        logger.info("SMTP Server Reachable : %s:%s", smtp_host, smtp_port)
        return True
    except Exception:
        logger.exception("SMTP server unreachable")
        return False


def validate(
    browser_data_dir: Path,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
) -> bool:
    """
    Pre-flight checks before a scan. SMTP reachability is only checked
    when settings are supplied - a scan can run (finding jobs) even
    before a user has configured SMTP; app/mailer.py separately refuses
    to send mail without settings.
    """

    logger.info("=" * 80)
    logger.info("SCAN VALIDATION")
    logger.info("=" * 80)

    status = True

    status &= check_file(MAIL_TEMPLATE, "Mail Template")
    status &= check_directory(browser_data_dir, "Browser Profile")
    status &= check_directory(LOG_DIR, "Logs Folder")
    status &= check_internet()

    if smtp_host and smtp_port:
        status &= check_smtp(smtp_host, smtp_port)

    logger.info("=" * 80)
    logger.info("Validation %s", "Successful" if status else "Failed")
    logger.info("=" * 80)

    return bool(status)
