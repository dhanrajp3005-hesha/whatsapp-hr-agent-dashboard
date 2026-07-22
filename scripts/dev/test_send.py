import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import (
    BREVO_SMTP_SERVER,
    BREVO_PORT,
    BREVO_USERNAME,
    BREVO_PASSWORD,
    FROM_EMAIL,
)

receiver_email = FROM_EMAIL

message = MIMEMultipart()
message["From"] = FROM_EMAIL
message["To"] = receiver_email
message["Subject"] = "Brevo SMTP Test - WhatsApp HR Bot"

body = """
Hello Dhanraj,

This is a test email sent successfully using Brevo SMTP.

If you received this email, your SMTP configuration is working correctly.

Regards,
WhatsApp HR Bot
"""

message.attach(MIMEText(body, "plain"))

try:
    server = smtplib.SMTP(BREVO_SMTP_SERVER, BREVO_PORT)
    server.starttls()
    server.login(BREVO_USERNAME, BREVO_PASSWORD)

    server.sendmail(
        FROM_EMAIL,
        receiver_email,
        message.as_string()
    )

    server.quit()

    print("=" * 60)
    print("✅ Test Email Sent Successfully")
    print("=" * 60)

except Exception as e:
    print("=" * 60)
    print("❌ Failed")
    print(e)
    print("=" * 60)
