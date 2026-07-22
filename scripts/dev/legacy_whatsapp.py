import time
from playwright.sync_api import sync_playwright

from app.search import open_community
from app.reader import read_messages
from app.parser import extract_emails


def open_whatsapp():

    print("=" * 80)
    print("Opening WhatsApp...")
    print("=" * 80)

    with sync_playwright() as p:

        browser = p.chromium.launch_persistent_context(
            user_data_dir="./browser_data",
            headless=False,
            channel="chrome"
        )

        page = browser.new_page()

        page.goto("https://web.whatsapp.com")

        page.wait_for_load_state("networkidle")

        print(f"Title : {page.title()}")
        print(f"URL   : {page.url}")

        # Open Community
        open_community(
            page,
            "Zenbyte Current Placement"
        )

        # Read Messages
        messages = read_messages(page)

        # Extract Email IDs
        emails = extract_emails(messages)

        print("=" * 80)
        print("EMAILS FOUND")
        print("=" * 80)

        if emails:
            for email in emails:
                print(email)
        else:
            print("No email IDs found.")

        print("=" * 80)
        print(f"Total Emails Found : {len(emails)}")
        print("=" * 80)

        browser.close()

        return emails


if __name__ == "__main__":

    emails = open_whatsapp()

    print("\nReturned Emails:")
    print(emails)
