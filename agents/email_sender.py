import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

SMTP_HOST = os.getenv("EMAIL_HOST")
SMTP_PORT = int(os.getenv("EMAIL_PORT", "587"))
SMTP_USER = os.getenv("EMAIL_USER")
SMTP_PASSWORD = os.getenv("EMAIL_PASSWORD")

CATEGORY_ICONS = {
    "tech": "🖥️",
    "geopolitics": "🌍",
    "sports": "🏅",
    "movies": "🎬",
}


def format_email(headlines):
    """
    headlines: list of {
        category, headline, link
    }
    """

    grouped = defaultdict(list)
    for h in headlines:
        grouped[h["category"]].append(h)

    body = "📰 Your News Digest\n\n"

    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(category, "📰")
        body += f"{icon} {category.upper()}\n"

        for item in items:
            body += f"• {item['headline']}\n"
            body += f"  {item['link']}\n"

        body += "\n"

    body += "—\nAI News Agent"

    return body


def send_email(to_email, headlines):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = "📰 Your News Digest"

    body = format_email(headlines)
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
