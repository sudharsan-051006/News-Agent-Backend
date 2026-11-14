"""
Email Delivery Engine for AI Trend Radar Agent.
Generates mobile-responsive HTML briefings with visual trend badges and delivers via SMTP.
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from config import settings

logger = logging.getLogger("agent.email")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Trend Radar</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f5f7; margin: 0; padding: 20px; color: #1e293b; }
        .container { max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        .header { background: linear-gradient(135deg, #0f172a, #1e293b); color: #ffffff; padding: 28px 24px; text-align: left; }
        .header h1 { margin: 0 0 6px 0; font-size: 24px; font-weight: 700; }
        .header p { margin: 0; font-size: 14px; color: #94a3b8; }
        .content { padding: 24px; }
        .exec-summary { background: #f8fafc; border-left: 4px solid #3b82f6; padding: 16px; border-radius: 6px; margin-bottom: 24px; }
        .exec-summary h3 { margin: 0 0 8px 0; font-size: 16px; color: #0f172a; }
        .exec-summary p { margin: 0; font-size: 14px; line-height: 1.5; color: #334155; }
        .card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin-bottom: 18px; }
        .badge { display: inline-block; padding: 3px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 8px; }
        .badge-breakout { background: #fee2e2; color: #dc2626; border: 1px solid #fecaca; }
        .badge-emerging { background: #fef3c7; color: #d97706; border: 1px solid #fde68a; }
        .badge-evolving { background: #e0e7ff; color: #4338ca; border: 1px solid #c7d2fe; }
        .badge-steady { background: #f1f5f9; color: #64748b; }
        .card h2 { margin: 4px 0 10px 0; font-size: 18px; color: #0f172a; }
        .card p { font-size: 14px; line-height: 1.6; color: #334155; margin: 0 0 12px 0; }
        .why-it-matters { background: #eff6ff; border-radius: 6px; padding: 10px 14px; font-size: 13px; color: #1e40af; }
        .why-it-matters strong { color: #1e3a8a; }
        .footer { padding: 20px 24px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Daily Trend Radar</h1>
            <p>6-Day Rolling Trend Intelligence &bull; {{ date_str }}</p>
        </div>
        <div class="content">
            <div class="exec-summary">
                <h3>Executive Trend Briefing</h3>
                <p>{{ executive_summary }}</p>
            </div>
            
            {{ body_html }}
            
        </div>
        <div class="footer">
            Delivered autonomously by your AI Trend Radar Agent &bull; Powered by Neon DB & LLM
        </div>
    </div>
</body>
</html>
"""


def send_trend_email(subject: str, executive_summary: str, body_html: str) -> bool:
    """Dispatches the formatted HTML trend briefing via SMTP."""
    if not settings.EMAIL_USER or not settings.EMAIL_PASSWORD or not settings.EMAIL_RECIPIENT:
        logger.warning("Email credentials not fully configured. Skipping delivery.")
        return False

    date_str = datetime.now().strftime("%B %d, %Y")
    html_content = (
        HTML_TEMPLATE.replace("{{ date_str }}", date_str)
                     .replace("{{ executive_summary }}", executive_summary)
                     .replace("{{ body_html }}", body_html)
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"AI Trend Radar <{settings.EMAIL_USER}>"
    msg["To"] = settings.EMAIL_RECIPIENT

    msg.attach(MIMEText(html_content, "html"))

    try:
        logger.info(f"Connecting to SMTP server {settings.EMAIL_HOST}:{settings.EMAIL_PORT}...")
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
            server.send_message(msg)
            logger.info(f"Daily trend briefing sent successfully to {settings.EMAIL_RECIPIENT}")
            return True
    except Exception as e:
        logger.error(f"Failed to dispatch email: {e}")
        return False
