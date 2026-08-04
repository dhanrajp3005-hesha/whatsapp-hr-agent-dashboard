from playwright.sync_api import Page

from app.logger import logger
from app.config import DEBUG


def read_messages(page: Page) -> list[dict]:
    """
    Read all visible WhatsApp messages. Each returned item is
    {"text": <full visible body>, "key": <stable per-message identity
    used for checkpointing - see the comment below>}.
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

            # data-pre-plain-text is WhatsApp's own "[H:MM am/pm,
            # DD/MM/YYYY] Sender: " metadata string, written into the DOM
            # by WhatsApp itself regardless of whether the message body
            # is truncated or expanded ("Read more"). Unlike the visible
            # body text, it can't change between two reads of the same
            # message, so checkpoint identity is based on it (plus a
            # truncation-safe prefix of the body, which is always
            # rendered even before expansion) instead of the full body -
            # which is exactly what kept breaking checkpoint matching:
            # a truncated vs. expanded read of the same message hashes
            # completely differently under the old text-only approach.
            metadata = element.get_attribute("data-pre-plain-text") or ""
            checkpoint_key = metadata + text[:120]

            messages.append({"text": text, "key": checkpoint_key})

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
            logger.info(message["text"])
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


def scroll_to_bottom(page: Page, max_jumps: int = 80) -> bool:
    """
    Jumps the open chat's message pane all the way down to the newest
    message before the checkpoint search begins. WhatsApp Web doesn't
    reliably open a chat scrolled to the bottom - a community/group
    with many unread messages is frequently opened scrolled to the
    *first* unread message instead, with genuinely newer messages still
    further down. Since collect_messages only ever scrolls up (toward
    older history), a checkpoint match found in a partial read would be
    misread as "caught up" while unread messages below it - the ones
    that actually matter - are silently never collected.

    A single scrollTop-to-scrollHeight jump is nowhere near enough:
    WhatsApp Web's virtualized list only pages in the *next* slice of
    newer messages once the pane actually reaches its current bottom
    edge, so reaching the true newest message can take dozens of
    repeated jumps when there's a real unread backlog. Confirmed live:
    repeated jumps against the same open community grew scrollHeight
    from 9470 all the way past 50000 over just 12 jumps without ever
    plateauing. Stopping after two jumps (the previous behaviour)
    landed on 9470 every single time regardless of how much unread
    content remained further down - exactly the stuck value that kept
    recurring across this bug's entire history. This mirrors scroll_up's
    own escalating-wait retry (1.5s/3s/5s) before concluding growth has
    truly stopped, since a lazy-load pause looks identical to genuinely
    reaching the end.
    """

    script = """
    () => {
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

        return { ok: true, scrollTop: target.scrollTop, scrollHeight: target.scrollHeight };
    }
    """

    def jump():
        try:
            return page.evaluate(script)
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    # The message pane sometimes isn't mounted yet the instant the chat
    # opens - retry a couple of times rather than treating one failed
    # detection as "pane doesn't exist" and falling back to a full,
    # unnecessary history re-scroll.
    result = None
    for attempt in range(3):
        result = jump()

        if result.get("ok"):
            break

        logger.warning(
            "scroll_to_bottom attempt %s/3 failed : %s", attempt + 1, result.get("reason")
        )
        page.wait_for_timeout(1000)

    if not result or not result.get("ok"):
        return False

    previous_height = result["scrollHeight"]

    for jump_count in range(1, max_jumps + 1):
        grew = False

        for wait_ms in (1500, 3000, 5000):
            page.wait_for_timeout(wait_ms)
            result = jump()

            if not result.get("ok"):
                logger.info(
                    "scroll_to_bottom result : %s (jump %s, pane gone)", result, jump_count
                )
                return True

            if result["scrollHeight"] > previous_height:
                grew = True
                break

        if not grew:
            logger.info(
                "scroll_to_bottom result : %s (reached true bottom after %s jump(s))",
                result, jump_count,
            )
            return True

        previous_height = result["scrollHeight"]

    logger.warning(
        "scroll_to_bottom : hit max_jumps (%s) without the pane ever stabilizing "
        "(scrollHeight=%s) - proceeding with what's loaded so far. Very large "
        "unread backlog?", max_jumps, previous_height,
    )
    return True


def wait_for_sync_to_settle(page, max_wait_seconds: int = 20, check_interval_seconds: int = 2) -> bool:
    """
    Waits until the message pane's (message count, scrollHeight) stops
    changing between two checks before letting the scan start reading.

    Every scan launches a brand-new browser page - the login session is
    persisted, but WhatsApp Web still has to re-establish its socket
    and re-sync the community's recent history from scratch each time.
    The fixed ~4s wait after opening a chat only confirms the UI is
    *interactive*, not that this specific community has finished
    syncing. Confirmed live: the exact same (scrollTop, scrollHeight)
    pair recurred byte-for-byte across scans spanning 5 separate days -
    far more consistent with "reading a not-yet-synced snapshot every
    time" than coincidence. This polls a cheap signature (no clicking,
    unlike read_messages) until it's stable, giving real sync time to
    catch up before anything is read for real.
    """

    script = """
    () => {
        const main = document.querySelector("#main");
        if (!main) return null;

        const count = main.querySelectorAll("div.copyable-text[data-pre-plain-text]").length;

        let scrollHeight = null;
        for (const el of main.querySelectorAll("*")) {
            if (el.scrollHeight > el.clientHeight + 100) {
                const style = getComputedStyle(el);
                if (style.overflowY === "auto" || style.overflowY === "scroll") {
                    scrollHeight = el.scrollHeight;
                    break;
                }
            }
        }

        return [count, scrollHeight];
    }
    """

    previous = None
    elapsed = 0

    while elapsed <= max_wait_seconds:
        try:
            current = page.evaluate(script)
        except Exception as e:
            logger.warning("wait_for_sync_to_settle: signature check errored : %s", e)
            current = None

        if current is not None and current == previous:
            logger.info(
                "wait_for_sync_to_settle: stable after %ss (count=%s, scrollHeight=%s)",
                elapsed, current[0], current[1],
            )
            return True

        previous = current
        page.wait_for_timeout(check_interval_seconds * 1000)
        elapsed += check_interval_seconds

    logger.warning(
        "wait_for_sync_to_settle: still changing after %ss - proceeding anyway "
        "(last signature: %s)", max_wait_seconds, previous,
    )
    return False

    return False
