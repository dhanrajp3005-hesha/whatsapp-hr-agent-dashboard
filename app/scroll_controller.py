from playwright.sync_api import Page

from app.reader import (
    read_messages,
    scroll_up,
)

from app.logger import logger
from app.config import (
    MAX_SCROLLS,
    SCROLL_DELAY,
)

from app.state import calculate_hash


def checkpoint_found(
    messages: list[str],
    last_hash: str,
) -> bool:
    """
    Check whether checkpoint message exists
    inside the current message list.
    """

    if not last_hash:
        return False

    for message in messages:

        if calculate_hash(message) == last_hash:
            return True

    return False


def merge_messages(
    existing: list[str],
    current: list[str],
) -> list[str]:
    """
    Merge messages while preserving order
    and removing duplicates.
    """

    seen = set()

    merged = []

    for message in existing + current:

        if message in seen:
            continue

        seen.add(message)
        merged.append(message)

    return merged
import time


def collect_messages(
    page: Page,
    last_hash: str,
) -> list[str]:
    """
    Read all WhatsApp messages by automatically scrolling
    until the previous checkpoint is found or the maximum
    scroll limit is reached.
    """

    logger.info("=" * 80)
    logger.info("Starting Auto Scroll Collection...")
    logger.info("=" * 80)

    all_messages = []

    for scroll_count in range(MAX_SCROLLS):

        logger.info(
            "Scroll %s / %s",
            scroll_count + 1,
            MAX_SCROLLS,
        )

        current_messages = read_messages(page)

        logger.info(
            "Visible Messages : %s",
            len(current_messages),
        )

        all_messages = merge_messages(
            all_messages,
            current_messages,
        )

        logger.info(
            "Merged Messages : %s",
            len(all_messages),
        )

        if checkpoint_found(
            all_messages,
            last_hash,
        ):
            logger.info(
                "Checkpoint found. Stopping scroll."
            )
            break

        if scroll_count == MAX_SCROLLS - 1:
            logger.info(
                "Maximum scroll limit reached."
            )
            break

        if not scroll_up(page):
            logger.warning(
                "Scroll failed. Stopping collection."
            )
            break

        time.sleep(SCROLL_DELAY)

    logger.info("=" * 80)
    logger.info(
        "Total Messages Collected : %s",
        len(all_messages),
    )
    logger.info("=" * 80)

    return all_messages
