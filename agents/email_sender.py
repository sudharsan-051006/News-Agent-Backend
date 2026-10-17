import os
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("EMAIL_HOST")
SMTP_USER = os.getenv("EMAIL_USER")
SMTP_PASSWORD = os.getenv("EMAIL_PASSWORD")

raw_port = os.getenv("EMAIL_PORT", "587")
SMTP_PORT = int(raw_port) if raw_port and raw_port.isdigit() else 587

if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
    raise RuntimeError("Missing EMAIL_* environment variables")

CATEGORY_ICONS = {
    "tech": "🖥️",
    "geopolitics": "🌍",
    "sports": "🏅",
    "movies": "🎬",
    "local": "IN",
}


def _safe_http_url(value):
    """Allow only absolute HTTP(S) URLs for links and image sources."""
    if not value:
        return None

    value = str(value).strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
        return value
    return None


def _image_html(image_url, headline):
    """Render an image only when a valid HTTP(S) URL was supplied."""
    safe_url = _safe_http_url(image_url)
    if not safe_url:
        return ""

    return f"""
      <img
        src="{escape(safe_url, quote=True)}"
        alt="{escape(str(headline or 'News image'), quote=True)}"
        width="560"
        style="display:block;width:100%;max-width:560px;height:auto;
               max-height:300px;object-fit:cover;border:0;border-radius:8px;
               margin:0 0 14px;"
      />
    """


def format_email_html(headlines):
    """Build a responsive-ish HTML digest grouped by category."""
    headlines = headlines or []
    grouped = defaultdict(list)
    for item in headlines:
        grouped[item.get("category") or "General"].append(item)

    total_images = sum(
        1 for item in headlines if _safe_http_url(item.get("image_url"))
    )
    print(
        f"🖼️ Email renderer received image URLs for "
        f"{total_images}/{len(headlines)} articles."
    )

    html_parts = ["""
    <!doctype html>
    <html>
    <body style="font-family:Arial,Helvetica,sans-serif;background:#eef1f5;
                 padding:24px;margin:0;">
      <div style="max-width:640px;margin:auto;background:#fff;border-radius:14px;
                  overflow:hidden;">
        <div style="background:#1a73e8;padding:28px 20px;text-align:center;color:#fff;">
          <h1 style="margin:0;font-size:26px;">📰 Your Daily News Digest</h1>
          <p style="margin:8px 0 0;font-size:14px;">Curated headlines just for you</p>
          <hr style="border:0;border-top:1px solid #ffffff66;margin:18px 0;">
          <a href="https://www.elinity.in/preferences" style="color:#fff;">
            Update your preferences
          </a>
        </div>
        <div style="padding:24px;">
    """]

    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(str(category).lower(), "📰")
        html_parts.append(f"""
          <div style="margin-bottom:32px;">
            <h3 style="margin:0 0 16px;font-size:18px;color:#333;
                       border-left:4px solid #1a73e8;padding-left:10px;">
              {escape(str(icon))} {escape(str(category).upper())}
            </h3>
        """)

        for item in items:
            headline = str(item.get("headline") or "Untitled")
            summary = str(item.get("summary") or "")
            link = _safe_http_url(item.get("link"))
            source = str(item.get("source") or "")
            image_html = _image_html(item.get("image_url"), headline)

            link_html = ""
            if link:
                link_html = f"""
                  <a href="{escape(link, quote=True)}"
                     style="display:inline-block;margin-top:12px;padding:8px 14px;
                            background:#1a73e8;color:#fff;text-decoration:none;
                            font-size:13px;border-radius:20px;">
                    Read full story →
                  </a>
                """

            source_html = (
                f'<p style="margin:0 0 8px;font-size:11px;color:#777;">'
                f'{escape(source)}</p>'
                if source else ""
            )

            html_parts.append(f"""
              <div style="background:#f9fafc;border-radius:10px;padding:16px;
                          margin-bottom:14px;border:1px solid #eef0f3;">
                {image_html}
                {source_html}
                <p style="margin:0;font-size:15px;line-height:1.5;color:#222;">
                  {escape(headline)}
                </p>
                <p style="margin:8px 0 0;font-size:13px;color:#555;line-height:1.5;">
                  {escape(summary)}
                </p>
                {link_html}
              </div>
            """)

        html_parts.append("</div>")

    html_parts.append("""
        </div>
        <div style="background:#f5f7fa;text-align:center;padding:18px;
                    font-size:12px;color:#777;">
          Sent with <strong>Elinity</strong><br>
          Stay informed. Stay ahead.
        </div>
      </div>
    </body>
    </html>
    """)

    return "".join(html_parts)


def send_email(to_email, headlines):
    """Send one user's personalized news digest as an HTML email."""
    if not to_email:
        raise ValueError("Recipient email address is required")

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = "📰 Your Daily News Digest"

    html_body = format_email_html(headlines)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

    print(f"✅ News digest sent to {to_email}")
