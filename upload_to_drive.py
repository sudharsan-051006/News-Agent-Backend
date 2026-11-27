"""Direct Google Drive Upload Utility for News-Agent-Backend.

Uploads generated news videos to your Google Drive folder:
https://drive.google.com/drive/folders/1jFFXoO2sqdDh3lpTcu40lRFTJmygIRRU

Supports:
1. Service Account (credentials.json)
2. Interactive OAuth browser login (client_secret.json -> token.json)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DEFAULT_FOLDER_ID = "1jFFXoO2sqdDh3lpTcu40lRFTJmygIRRU"
SCOPES = ["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]


def get_drive_service():
    """Authenticate and return Google Drive API v3 service."""
    from googleapiclient.discovery import build

    # Check 1: Service Account credentials.json
    service_acc_file = os.getenv("GDRIVE_CREDENTIALS_FILE", "credentials.json")
    if os.path.exists(service_acc_file):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(service_acc_file, scopes=SCOPES)
        print(f"🔑 Using Service Account from: {service_acc_file}")
        return build("drive", "v3", credentials=creds)

    # Check 2: OAuth token.json / client_secret.json
    token_file = "token.json"
    client_secret_file = os.getenv("GDRIVE_CLIENT_SECRET", "client_secret.json")

    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_file):
                return None
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_video_file(file_path: str, folder_id: str = DEFAULT_FOLDER_ID) -> str | None:
    path = Path(file_path)
    if not path.exists():
        print(f"❌ File not found: {file_path}")
        return None

    service = get_drive_service()
    if not service:
        print("\n" + "=" * 65)
        print("⚠️ GOOGLE DRIVE AUTHENTICATION NEEDED")
        print("=" * 65)
        print("Google Drive does not allow anonymous file uploads via URL link.")
        print("To enable automatic Python uploads directly into your folder:")
        print("  1. Download a 'credentials.json' (Service Account) OR 'client_secret.json' (OAuth)")
        print("     from Google Cloud Console (https://console.cloud.google.com/apis/credentials).")
        print("  2. Place it inside: D:\\AI PYTHON PROJECTS\\News-Agent-Backend\\credentials.json")
        print(f"  3. Share your folder with your Service Account email address as 'Editor'.")
        print("\nFor now, you can simply drag & drop the video into your Drive folder:")
        print(f"  Local file:   {path.resolve()}")
        print(f"  Drive folder: https://drive.google.com/drive/folders/{folder_id}")
        print("=" * 65 + "\n")
        return None

    from googleapiclient.http import MediaFileUpload

    file_metadata = {
        "name": path.name,
        "parents": [folder_id],
    }
    media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)

    print(f"🚀 Uploading {path.name} to Google Drive folder: {folder_id}...")
    file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()

    web_link = file.get("webViewLink") or f"https://drive.google.com/file/d/{file.get('id')}/view"
    print(f"✅ Upload Complete! File link: {web_link}")
    return web_link


if __name__ == "__main__":
    latest_video = "outputs/top25_news_bulletin_20261127_110844.mp4"
    target_folder = os.getenv("GDRIVE_FOLDER_ID", DEFAULT_FOLDER_ID)
    if "folders/" in target_folder:
        target_folder = target_folder.split("folders/")[1].split("?")[0].strip()

    upload_video_file(latest_video, folder_id=target_folder)
