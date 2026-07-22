from playwright.sync_api import Page, TimeoutError

from app.logger import logger

SEARCH_BOX = "Search or start a new chat"


def dismiss_popups(page: Page) -> None:
    """
    WhatsApp Web occasionally shows a blocking modal dialog on load -
    e.g. a "What's new on WhatsApp Web" announcement - which intercepts
    every click, including the search box, until closed. Best-effort:
    does nothing if no dialog is present.
    """

    try:
        close_button = page.locator("div[role='dialog'] button[aria-label='Close']").first
        if close_button.count() > 0 and close_button.is_visible():
            close_button.click(timeout=3000)
            page.wait_for_timeout(500)
            logger.info("Dismissed a blocking WhatsApp Web dialog.")
    except Exception:
        pass


def list_communities(page: Page) -> list[str]:
    """
    Best-effort discovery of community/group names visible in the
    current WhatsApp account's chat list sidebar, for the onboarding
    community picker. WhatsApp Web's DOM/selectors change over time
    (the same fragility already present in open_community below) - if
    this stops finding anything after a WhatsApp Web UI update, the
    selector is the first thing to check.
    """

    logger.info("Discovering communities/groups in chat list...")

    try:
        page.get_by_role("textbox", name=SEARCH_BOX).wait_for(timeout=15000)
    except TimeoutError:
        logger.error("Chat list not ready - cannot discover communities.")
        return []

    page.wait_for_timeout(1000)

    titles = page.locator(
        '[aria-label="Chat list"] span[dir="auto"][title]'
    ).all()

    names: list[str] = []
    seen = set()

    for title in titles:
        try:
            name = title.get_attribute("title")
        except Exception:
            continue

        if not name or name in seen:
            continue

        seen.add(name)
        names.append(name)

    logger.info("Discovered %s chat(s)/communit(y/ies).", len(names))
    return names


def open_community(page: Page, community_name: str) -> None:
    """
    Search and open the specified WhatsApp community/chat.
    Compatible with the latest WhatsApp Web UI.
    """

    logger.info("Searching for community: %s", community_name)

    dismiss_popups(page)

    try:
        search_box = page.get_by_role(
            "textbox",
            name=SEARCH_BOX,
        )

        search_box.wait_for(timeout=15000)

        logger.info("Search box found.")

        # Clear previous search
        search_box.click()
        search_box.press("Control+A")
        search_box.press("Backspace")

        # Type community name
        search_box.fill(community_name)

        logger.info("Typed community name.")

        page.wait_for_timeout(1500)

        # Click the ACTUAL chat item instead of recent-search item
        chat = page.locator(
            f"span[title='{community_name}']"
        ).last

        chat.wait_for(timeout=10000)

        logger.info("Community found.")

        chat.scroll_into_view_if_needed()

        chat.click()

        logger.info(
            "Community opened successfully : %s",
            community_name,
        )

    except TimeoutError as e:

        logger.error(
            "Timeout while opening community '%s'",
            community_name,
        )

        raise TimeoutError(
            f"Community '{community_name}' not found."
        ) from e

    except Exception:

        logger.exception(
            "Unexpected error while opening community '%s'",
            community_name,
        )

        raise
