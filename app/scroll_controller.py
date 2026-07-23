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
    Merge messages while preserving chronological order and removing
    duplicates. Scrolling always reveals OLDER messages above what's
    already known, so anything in `current` not already in `existing`
    must be older than everything in `existing` - it belongs before
    it, not after. Appending instead (the original approach) scrambled
    order across multiple scroll rounds: scanner.py's new-message
    extraction walks this list assuming oldest-first, so genuinely new
    messages could end up positioned before an old checkpoint match
    and get silently excluded.
    """

    existing_set = set(existing)

    new_from_current = [
        message for message in current if message not in existing_set
    ]

    return new_from_current + existing
import time


def collect_messages(
    page: Page,
    last_hash: str,
) -> tuple[list[str], bool]:
    """
    Read all WhatsApp messages by automatically scrolling until the
    previous checkpoint is found or the maximum scroll limit is
    reached. Returns (messages, found) - callers must check `found`
    before trusting "everything after the checkpoint is new" logic: if
    the checkpoint was never located (very high-volume chat outpacing
    MAX_SCROLLS, or a stalled scroll), silently treating that as "no
    new messages" would be wrong - see scanner.py's fallback.
    """

    logger.info("=" * 80)
    logger.info("Starting Auto Scroll Collection...")
    logger.info("=" * 80)

    all_messages = []
    found = last_hash == ""

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
            found = True
            break

        if scroll_count == MAX_SCROLLS - 1:
            logger.warning(
                "Maximum scroll limit reached without finding checkpoint."
            )
            break

        if not scroll_up(page):
            logger.warning(
                "Scroll stalled (no more history to load) without finding checkpoint."
            )
            break

        time.sleep(SCROLL_DELAY)

    logger.info("=" * 80)
    logger.info(
        "Total Messages Collected : %s (checkpoint found: %s)",
        len(all_messages),
        found,
    )
    logger.info("=" * 80)

    return all_messages, found
