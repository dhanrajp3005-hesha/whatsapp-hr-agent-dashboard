from playwright.sync_api import Page

from app.logger import logger
from app.config import DEBUG


def read_messages(page: Page) -> list[str]:
    """
    Read all visible WhatsApp messages.
    """

    logger.info("=" * 80)
    logger.info("Reading WhatsApp Messages...")
    logger.info("=" * 80)

    # ------------------------------------------------------
    # Expand Read More
    # ------------------------------------------------------

    try:

        buttons = page.get_by_text("Read more").all()

        logger.info(
            "Read More buttons found : %s",
            len(buttons),
        )

        for button in buttons:

            try:
                button.click(timeout=1000)
            except Exception:
                pass

    except Exception as e:

        logger.warning(
            "Unable to expand Read More buttons : %s",
            e,
        )

    page.wait_for_timeout(1500)

    # ------------------------------------------------------
    # Read WhatsApp Messages
    # ------------------------------------------------------

    elements = page.locator(
        "div.copyable-text[data-pre-plain-text]"
    ).all()

    logger.info(
        "Filtered Messages : %s",
        len(elements),
    )

    messages = []

    for element in elements:

        try:

            text = element.inner_text().strip()

            if not text:
                continue

            messages.append(text)

        except Exception:
            continue

    logger.info(
        "Collected Messages : %s",
        len(messages),
    )

    # ------------------------------------------------------
    # Debug Output
    # ------------------------------------------------------

    if DEBUG:

        logger.info("=" * 80)
        logger.info("VISIBLE WHATSAPP MESSAGES")
        logger.info("=" * 80)

        for index, message in enumerate(messages, start=1):

            logger.info("")
            logger.info("MESSAGE %s", index)
            logger.info("-" * 60)
            logger.info(message)
            logger.info("-" * 60)

    logger.info("=" * 80)
    logger.info("Finished Reading WhatsApp Messages")
    logger.info("=" * 80)

    return messages

from playwright.sync_api import Page

from app.logger import logger


def scroll_up(page: Page) -> bool:

    try:

        result = page.evaluate("""
        () => {

            const main = document.querySelector("#main");

            if (!main)
                return "MAIN NOT FOUND";

            function walk(node, depth = 0) {

                const items = [];

                for (const child of node.children) {

                    items.push({
                        tag: child.tagName,
                        id: child.id,
                        testid: child.getAttribute("data-testid"),
                        class: child.className,
                        scrollHeight: child.scrollHeight,
                        clientHeight: child.clientHeight
                    });

                    items.push(...walk(child, depth + 1));
                }

                return items;
            }

            return walk(main);

        }
        """)

        logger.info("=" * 80)
        logger.info(result)
        logger.info("=" * 80)

        return False

    except Exception as e:

        logger.exception(e)

        return False
