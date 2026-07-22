from playwright.sync_api import sync_playwright

from app.waiter import wait_for_whatsapp
from app.search import open_community
from app.reader import read_messages
from app.parser import extract_emails, extract_job_details
from app.excel import save_jobs
from app.mailer import send_emails
from app import cache


def scan_whatsapp():

    print("=" * 80)
    print("Starting WhatsApp Scan...")
    print("=" * 80)

    with sync_playwright() as p:

        browser = p.chromium.launch_persistent_context(
            user_data_dir="./browser_data",
            headless=False,
            channel="chrome"
        )

        page = browser.new_page()

        page.goto("https://web.whatsapp.com")

        print(f"Title : {page.title()}")
        print(f"URL   : {page.url}")

        # --------------------------------------------------------
        # Wait until WhatsApp UI is fully ready
        # --------------------------------------------------------

        wait_for_whatsapp(page)

        # --------------------------------------------------------
        # Open Community
        # --------------------------------------------------------

        open_community(
            page,
            "Zenbyte Current Placement"
        )

        # --------------------------------------------------------
        # Read WhatsApp Messages
        # --------------------------------------------------------

        messages = read_messages(page)

        # --------------------------------------------------------
        # Extract Emails & Jobs
        # --------------------------------------------------------

        emails = extract_emails(messages)
        jobs = extract_job_details(messages)

        # --------------------------------------------------------
        # Save Jobs to Excel
        # --------------------------------------------------------

        save_jobs(jobs)

        # --------------------------------------------------------
        # Automatically Send Pending Emails
        # --------------------------------------------------------

        print("=" * 80)
        print("Starting Mail Sender...")
        print("=" * 80)

        send_emails()

        # --------------------------------------------------------
        # Update Cache
        # --------------------------------------------------------

        cache.emails = emails
        cache.jobs = jobs

        browser.close()

    print("=" * 80)
    print(f"WhatsApp Scan Completed - {len(jobs)} Jobs Found")
    print("=" * 80)

    return jobs
