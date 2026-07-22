from playwright.sync_api import Page

from app.logger import logger


def read_messages(page: Page) -> list[str]:
    """
    Read all visible WhatsApp messages.

    Each WhatsApp message is returned as an individual item.
    No merging is performed.
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

    elements = page.locator("[data-pre-plain-text]").all()

    logger.info(
        "DOM Messages Found : %s",
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
