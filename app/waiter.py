from playwright.sync_api import Page
import time


def wait_for_whatsapp(page: Page, timeout: int = 60):

    print("=" * 80)
    print("Waiting for WhatsApp UI...")
    print("=" * 80)

    start = time.time()

    while time.time() - start < timeout:

        try:
            print("Title :", page.title())

            print(
                "Textbox count :",
                page.get_by_role("textbox").count()
            )

            print(
                "Editable count :",
                page.locator('[contenteditable="true"]').count()
            )

            if page.get_by_role("textbox").count() > 0:
                print("✅ WhatsApp Ready")
                return

        except Exception as e:
            print(e)

        page.wait_for_timeout(2000)

    raise Exception("WhatsApp UI timeout")
