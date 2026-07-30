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

        # Scoped to #main (the open conversation pane) - page-wide
        # get_by_text also matches unrelated "Read more" text in
        # WhatsApp Web's sidebar chat-list previews. Confirmed live:
        # one read reported 16 "Read more" matches for a total of only
        # 5 real messages, which is impossible if each message has at
        # most one - the extra 11 were never going to disappear no
        # matter how many times they were "clicked", which is exactly
        # what was tripping the loop's safety valve below every time.
        chat_pane = page.locator("#main")

        initial_count = chat_pane.get_by_text("Read more").count()

        logger.info(
            "Read More buttons found : %s",
            initial_count,
        )

        expanded = 0
        failed = 0

        # Re-locate the first remaining "Read more" element fresh on
        # every iteration rather than clicking through a list collected
        # up front - expanding one message reflows the page (WhatsApp
        # Web's virtualized list can even detach/replace nearby message
        # nodes), so element handles collected before any clicks happen
        # regularly go stale for everything after the first. That stale-
        # handle click is exactly what was timing out and leaving
        # messages un-expanded (confirmed live: 8 of 16 failed to expand
        # in one scan, each with a hash that won't match this same
        # message's hash from a scan where it did expand).
        while True:

            remaining = chat_pane.get_by_text("Read more")

            if remaining.count() == 0:
                break

            clicked = False

            for attempt in range(2):
                try:
                    remaining.first.click(timeout=2000)
                    clicked = True
                    break
                except Exception:
                    pass

            if clicked:
                expanded += 1
                page.wait_for_timeout(200)
            else:
                # This specific element won't click even on retry - it'll
                # still be "first" next loop, so stop rather than spin.
                failed += 1
                break

            if expanded + failed > initial_count + 5:
                # Safety valve - should never trigger, guards against an
                # infinite loop if some "Read more" element can never be
                # made to disappear (e.g. click lands but doesn't expand).
                logger.warning("Read More expansion loop exceeded expected count - stopping.")
                break

        if failed:
            # A message left un-expanded here gets hashed in its
            # truncated form. If a later scan expands it successfully,
            # that same message hashes differently - permanently
            # breaking checkpoint matching for it. Surfacing the count
            # makes that failure mode diagnosable instead of silent.
            logger.warning(
                "Could not expand %s 'Read more' message(s) (%s expanded of %s found) - "
                "their hash may be unstable across scans.",
                failed, expanded, initial_count,
            )

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


def scroll_to_bottom(page: Page) -> bool:
    """
    Jumps the open chat's message pane to the newest message before the
    checkpoint search begins. WhatsApp Web doesn't reliably open a chat
    scrolled to the bottom - a community/group with many unread
    messages is frequently opened scrolled to the *first* unread
    message instead, with genuinely newer messages still further down.
    Since collect_messages only ever scrolls up (toward older history),
    a checkpoint match found in that first, partial read would be
    misread as "caught up" while unread messages below it - the ones
    that actually matter - are silently never collected. Confirmed live:
    a scan reported 0 new messages despite messages having arrived
    hours earlier, and the very next scan (checkpoint no longer
    reachable at all) picked up dozens of them at once.
    """

    script = """
    async () => {
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

        target.scrollTop = target.scrollHeight;
        await new Promise((resolve) => setTimeout(resolve, 1000));
        target.scrollTop = target.scrollHeight;

        return { ok: true, scrollTop: target.scrollTop, scrollHeight: target.scrollHeight };
    }
    """

    # The message pane sometimes isn't mounted yet the instant the chat
    # opens - retry a couple of times rather than treating one failed
    # detection as "pane doesn't exist" and falling back to a full,
    # unnecessary history re-scroll.
    for attempt in range(3):
        try:
            result = page.evaluate(script)
        except Exception as e:
            logger.warning("scroll_to_bottom attempt %s errored : %s", attempt + 1, e)
            result = {"ok": False, "reason": str(e)}

        if result.get("ok"):
            logger.info("scroll_to_bottom result : %s", result)
            return True

        logger.warning(
            "scroll_to_bottom attempt %s/3 failed : %s", attempt + 1, result.get("reason")
        )
        page.wait_for_timeout(1000)

    return False
