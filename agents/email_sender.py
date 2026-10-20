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

# ---------------------------------------------------------------------------
# Design tokens — mirror Dashboard.css (editorial dark, vermilion accent).
# Emails can't use CSS variables or rgba() reliably, so these are solid colors.
# ---------------------------------------------------------------------------
FONT = "'Manrope','Helvetica Neue',Helvetica,Arial,sans-serif"
FONT_DISPLAY = "'Space Grotesk','Helvetica Neue',Helvetica,Arial,sans-serif"
FONT_MONO = "'IBM Plex Mono',Menlo,Consolas,'Courier New',monospace"

COLOR_PAGE_BG = "#000000"      # --bg
COLOR_PANEL = "#0a0a0a"        # --panel
COLOR_PANEL_2 = "#111111"      # --panel-2
COLOR_BORDER = "#1f1f1f"       # --line (solid equivalent)
COLOR_BORDER_2 = "#2a2a2a"     # --line-2 (solid equivalent)
COLOR_TEXT = "#ffffff"         # --ink
COLOR_TEXT_2 = "#d0d0d0"       # --ink-2
COLOR_MUTED = "#9a9a9a"        # --muted
COLOR_ACCENT = "#e11d2e"       # --accent
COLOR_ACCENT_LIGHT = "#ff7b85"
COLOR_ACCENT_BG = "#2a0f12"    # --accent-soft on black


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
               max-height:300px;object-fit:cover;border:0;
               border-radius:16px 16px 0 0;margin:0;"
      />
    """


def _logo_html():
    """The Elinity 'E' monogram (three red bars) followed by 'linity'."""
    bar = (
        'style="height:4px;line-height:4px;font-size:0;'
        'background:{c};border-radius:2px;"'
    )
    return f"""
          <table role="presentation" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td valign="middle" style="padding-right:8px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="25">
                  <tr><td width="25" bgcolor="{COLOR_ACCENT}" {bar.format(c=COLOR_ACCENT)}>&nbsp;</td></tr>
                  <tr><td height="4" style="height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr>
                  <tr><td align="left" style="font-size:0;line-height:0;">
                    <!-- Shorter middle bar: nested table so its width isn't stretched to the column -->
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="15">
                      <tr><td width="15" bgcolor="{COLOR_ACCENT}" {bar.format(c=COLOR_ACCENT)}>&nbsp;</td></tr>
                    </table>
                  </td></tr>
                  <tr><td height="4" style="height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr>
                  <tr><td width="25" bgcolor="{COLOR_ACCENT}" {bar.format(c=COLOR_ACCENT)}>&nbsp;</td></tr>
                </table>
              </td>
              <td valign="middle"
                  style="font-family:{FONT_DISPLAY};font-size:28px;line-height:1;
                         letter-spacing:-0.5px;color:{COLOR_TEXT};">
                linity
              </td>
            </tr>
          </table>
    """


def format_email_html(headlines):
    """Build an HTML digest grouped by category, styled like the dashboard."""
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

    html_parts = [f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <meta name="color-scheme" content="dark">
      <meta name="supported-color-schemes" content="dark">
      <title>Your Daily News Digest</title>
    </head>
    <body bgcolor="{COLOR_PAGE_BG}"
          style="font-family:{FONT};background:{COLOR_PAGE_BG};
                 padding:24px 12px;margin:0;color:{COLOR_TEXT};">
      <div style="max-width:640px;margin:auto;">

        <!-- Header -->
        <div style="background:{COLOR_PANEL_2};border:1px solid {COLOR_BORDER};
                    border-top:3px solid {COLOR_ACCENT};border-radius:24px;
                    padding:32px 28px;margin-bottom:24px;color:{COLOR_TEXT};">
          {_logo_html()}
          <div style="font-family:{FONT_MONO};font-size:10px;font-weight:700;
                      letter-spacing:1.8px;color:{COLOR_MUTED};margin:28px 0 10px;">
            YOUR DAILY BRIEFING
          </div>
          <h1 style="margin:0;font-family:{FONT_DISPLAY};font-size:34px;
                     line-height:1.1;font-weight:500;letter-spacing:-0.5px;
                     color:{COLOR_TEXT};">
            Stories worth your time.
          </h1>
          <p style="margin:14px 0 0;font-size:14px;line-height:1.6;
                    color:{COLOR_TEXT_2};">
            Curated headlines just for you
          </p>
          <p style="margin:20px 0 0;font-size:13px;">
            <a href="https://www.elinity.in/"
               style="display:inline-block;padding:9px 16px;border:1px solid {COLOR_BORDER_2};
                      border-radius:999px;color:{COLOR_TEXT};text-decoration:none;
                      font-weight:600;">
              Update your preferences
            </a>
          </p>
        </div>
    """]

    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(str(category).lower(), "📰")
        html_parts.append(f"""
        <div style="margin:0 0 30px;">
          <div style="font-family:{FONT_MONO};font-size:10px;font-weight:700;
                      letter-spacing:1.8px;color:{COLOR_ACCENT};margin:0 0 6px;
                      padding:0 4px;">
            CURATED FOR YOU
          </div>
          <h2 style="margin:0 0 16px;padding:0 4px;font-family:{FONT_DISPLAY};
                     font-size:26px;font-weight:500;letter-spacing:-0.4px;
                     color:{COLOR_TEXT};text-transform:capitalize;">
            {escape(str(icon))} {escape(str(category))}
          </h2>
        """)

        for item in items:
            headline = str(item.get("headline") or "Untitled")
            summary = str(item.get("summary") or "")
            link = _safe_http_url(item.get("link"))
            image_html = _image_html(item.get("image_url"), headline)

            # Headline links to the article when a valid article URL exists.
            if link:
                title_html = (
                    f'<a href="{escape(link, quote=True)}" '
                    f'style="color:{COLOR_TEXT};text-decoration:none;">'
                    f'{escape(headline)}</a>'
                )
            else:
                title_html = escape(headline)

            # Article link only (the RSS source link is intentionally not shown).
            link_html = ""
            if link:
                link_html = f"""
                  <a href="{escape(link, quote=True)}"
                     style="display:inline-block;margin-top:16px;padding:11px 20px;
                            background:{COLOR_TEXT};color:#000000;
                            text-decoration:none;font-size:13px;font-weight:700;
                            border-radius:999px;">
                    Read original article →
                  </a>
                """

            category_chip_html = (
                f'<span style="display:inline-block;margin:0 0 12px;padding:5px 9px;'
                f'background:{COLOR_ACCENT_BG};border:1px solid #5a1a21;'
                f'border-radius:6px;font-family:{FONT_MONO};font-size:9px;'
                f'font-weight:700;letter-spacing:1.1px;color:{COLOR_ACCENT_LIGHT};'
                f'text-transform:uppercase;">{escape(str(category))}</span>'
            )

            summary_html = (
                f'<p style="margin:12px 0 0;font-size:14px;line-height:1.7;'
                f'color:{COLOR_TEXT_2};">{escape(summary)}</p>'
                if summary else ""
            )

            html_parts.append(f"""
          <div style="background:{COLOR_PANEL};border:1px solid {COLOR_BORDER};
                      border-radius:16px;margin:0 0 16px;overflow:hidden;">
            {image_html}
            <div style="padding:20px 22px 22px;">
              <p style="margin:0;font-family:{FONT_DISPLAY};font-size:20px;
                        line-height:1.35;font-weight:600;letter-spacing:-0.2px;
                        color:{COLOR_TEXT};">
                {title_html}
              </p>
              {summary_html}
              {link_html}
            </div>
          </div>
            """)

        html_parts.append("</div>")

    html_parts.append(f"""
        <!-- Footer -->
        <div style="text-align:center;padding:22px 12px;font-size:12px;
                    color:{COLOR_MUTED};border-top:1px solid {COLOR_BORDER};">
          Made for curious minds &middot;
          <strong style="color:{COLOR_TEXT};">Elinity</strong><br>
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