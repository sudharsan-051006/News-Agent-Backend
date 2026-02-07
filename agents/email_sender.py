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
    <body style="
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
        background:#eef1f5;
        padding:24px;
        margin:0;
    ">
      <div style="
          max-width:640px;
          margin:auto;
          background:#ffffff;
          border-radius:14px;
          overflow:hidden;
          box-shadow:0 8px 30px rgba(0,0,0,0.08);
      ">

        <!-- Header -->
        <div style="
            background:linear-gradient(135deg,#1a73e8,#6c63ff);
            padding:28px 20px;
            text-align:center;
            color:#ffffff;
        ">
          <h1 style="margin:0;font-size:26px;">📰 Your Daily News Digest</h1>
          <p style="margin:8px 0 0;font-size:14px;opacity:0.9;">
            Curated headlines just for you
          </p>
          <hr></hr>
          <a href="https://news-agents-five.vercel.app/">To Update Your Perferences</a>
        </div>

        <!-- Content -->
        <div style="padding:24px;">
    """

    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(category, "📰")

        html += f"""
        <div style="margin-bottom:32px;">
          <h3 style="
              margin:0 0 16px;
              font-size:18px;
              color:#333;
              border-left:4px solid #6c63ff;
              padding-left:10px;
          ">
            {icon} {category.upper()}
          </h3>
        """

        for item in items:
            html += f"""
            <div style="
                background:#f9fafc;
                border-radius:10px;
                padding:16px;
                margin-bottom:14px;
                border:1px solid #eef0f3;
            ">
              <p style="
                  margin:0;
                  font-size:15px;
                  line-height:1.5;
                  color:#222;
              ">
                {item['headline']}
              </p>

              <a href="{item['link']}" style="
                  display:inline-block;
                  margin-top:12px;
                  padding:8px 14px;
                  background:#1a73e8;
                  color:#ffffff;
                  text-decoration:none;
                  font-size:13px;
                  border-radius:20px;
              ">
                Read full story →
              </a>
            </div>
            """

        html += "</div>"

    html += """
        </div>

        <!-- Footer -->
        <div style="
            background:#f5f7fa;
            text-align:center;
            padding:18px;
            font-size:12px;
            color:#777;
        ">
          Sent with <strong>AI News Agent</strong><br/>
          Stay informed. Stay ahead.
        </div>

      </div>
    </body>
    </html>
    """

    return html


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
