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
    """
    Scrolls the open chat's message pane to the top to trigger WhatsApp
    Web's lazy-loading of older messages, then reports whether new
    content actually appeared. Retries with increasingly long waits
    before concluding there's truly no more history - a single
    no-growth reading isn't reliable on its own (confirmed live: the
    exact same scroll that reported no growth after 1.5s reliably
    grows given more time - WhatsApp's lazy-load timing varies, and a
    transient hiccup looks identical to genuinely reaching the top).
    """

    try:
        for wait_ms in (1500, 3000, 5000):
            result = page.evaluate(
                """
            async (waitMs) => {
                const main = document.querySelector("#main");
                if (!main) return { ok: false, reason: "main not found" };

                let target = null;
                for (const el of main.querySelectorAll("*")) {
                    if (el.scrollHeight > el.clientHeight + 100) {
                        const style = getComputedStyle(el);
                        if (style.overflowY === "auto" || style.overflowY === "scroll") {
                            target = el;
                            break;
                        }
                    }
                }

                if (!target) return { ok: false, reason: "no scrollable pane found" };

                const before = target.scrollHeight;
                target.scrollTop = 0;

                await new Promise((resolve) => setTimeout(resolve, waitMs));

                return {
                    ok: true,
                    grew: target.scrollHeight > before,
                    before: before,
                    after: target.scrollHeight,
                };
            }
            """,
                wait_ms,
            )

            if not result.get("ok"):
                logger.warning("Unable to scroll : %s", result.get("reason"))
                return False

            if result.get("grew"):
                logger.info("scroll_up result : %s (wait=%sms)", result, wait_ms)
                return True

            logger.info("No growth after %sms - retrying with a longer wait...", wait_ms)

        logger.info("No growth after retries - reached the top of history.")
        return False

    except Exception as e:

        logger.exception(e)

        return False
