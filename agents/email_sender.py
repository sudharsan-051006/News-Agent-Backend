import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# --- Email configuration ---
SMTP_HOST = os.getenv("EMAIL_HOST")
SMTP_USER = os.getenv("EMAIL_USER")
SMTP_PASSWORD = os.getenv("EMAIL_PASSWORD")

raw_port = os.getenv("EMAIL_PORT", "587")
SMTP_PORT = int(raw_port) if raw_port and raw_port.isdigit() else 587

if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
    raise RuntimeError("❌ Missing EMAIL_* environment variables")

# --- Category icons ---
CATEGORY_ICONS = {
    "tech": "🖥️",
    "geopolitics": "🌍",
    "sports": "🏅",
    "movies": "🎬",
    "local" : "IN",
}


def format_email_html(headlines):
    grouped = defaultdict(list)
    for h in headlines:
        grouped[h["category"]].append(h)

    html = """
    <html>
    <body style="font-family: Arial, sans-serif; background:#f4f6f8; padding:20px;">
      <div style="max-width:600px;margin:auto;">
        <h2 style="text-align:center;">📰 Your News Digest</h2>
    """

    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(category, "📰")

        html += f"""
        <h3 style="margin-top:30px;">{icon} {category.upper()}</h3>
        """

        for item in items:
            html += f"""
            <div style="
              background:#ffffff;
              border-radius:8px;
              padding:15px;
              margin-bottom:12px;
              box-shadow:0 2px 6px rgba(0,0,0,0.08);
            ">
              <p style="margin:0;font-size:15px;">
                {item['headline']}
              </p>
              <a href="{item['link']}"
                 style="
                   display:inline-block;
                   margin-top:8px;
                   color:#1a73e8;
                   text-decoration:none;
                   font-size:14px;
                 ">
                 Read more →
              </a>
            </div>
            """

    html += """
        <p style="text-align:center;color:#777;font-size:12px;margin-top:30px;">
          — AI News Agent
        </p>
      </div>
    </body>
    </html>
    """

    return html

    return body


def send_email(to_email, headlines):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = "📰 Your News Digest"
    
    html_body = format_email_html(headlines)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
