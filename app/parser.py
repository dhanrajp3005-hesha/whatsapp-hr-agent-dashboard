import re
from datetime import datetime

from app.logger import logger

EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


def extract_jobs(messages):
    """
    Extract only email addresses from WhatsApp messages.

    Returns:
    [
        {
            "date": "...",
            "email": "...",
            "status": "Pending"
        }
    ]
    """

    jobs = []

    seen = set()

    current_time = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    for message in messages:

        emails = EMAIL_PATTERN.findall(message)

        if not emails:
            continue

        for email in emails:

            email = email.lower().strip()

            if email in seen:
                continue

            seen.add(email)

            jobs.append(
                {
                    "date": current_time,
                    "email": email,
                    "status": "Pending",
                }
            )

            logger.info(
                "Email Found : %s",
                email,
            )

    logger.info(
        "Total Emails Extracted : %s",
        len(jobs),
    )

    return jobs
