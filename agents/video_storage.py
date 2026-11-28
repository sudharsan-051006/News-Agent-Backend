"""Video Storage & Distribution Manager for News-Agent-Backend.

Provides dual-destination storage for generated broadcast videos:
1. Supabase Storage (Built-in Public CDN):
   - Direct integration using existing project credentials in .env.
   - Returns high-speed CDN streaming URL for instant HTML5 playback in news_web.
   - Automatically tracks video records in Supabase database.
2. Google Drive Storage:
   - Supports uploading to a designated Google Drive folder link or folder ID.
   - Uses Google Drive API (Service Account or OAuth) when credentials are provided.
"""
from __future__ import annotations

import os
import sys
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from supabase_client import supabase

DEFAULT_BUCKET_NAME = "news_videos"


# =====================================================================
# SUPABASE STORAGE & DATABASE INTEGRATION (RECOMMENDED FOR NEWS_WEB)
# =====================================================================

def ensure_supabase_bucket(bucket_name: str = DEFAULT_BUCKET_NAME) -> bool:
    """Ensure that the public Supabase storage bucket exists."""
    try:
        buckets = supabase.storage.list_buckets()
        existing = [b.name for b in buckets]
        if bucket_name not in existing:
            print(f"📦 Creating public Supabase storage bucket '{bucket_name}'...")
            supabase.storage.create_bucket(bucket_name, options={"public": True})
            print(f"✅ Supabase bucket '{bucket_name}' created successfully.")
        return True
    except Exception as exc:
        print(f"⚠️ Note on bucket check ({bucket_name}): {exc}")
        return False


def upload_to_supabase_storage(
    local_file_path: str,
    destination_name: Optional[str] = None,
    bucket_name: str = DEFAULT_BUCKET_NAME,
) -> Tuple[bool, str]:
    """Upload generated broadcast video to Supabase Storage and return public CDN URL.

    Returns:
        Tuple of (success_boolean, public_url_or_error)
    """
    path = Path(local_file_path)
    if not path.exists():
        return False, f"File does not exist: {local_file_path}"

    dest_name = destination_name or path.name
    ensure_supabase_bucket(bucket_name)

    print(f"🚀 Uploading video ({path.stat().st_size / (1024*1024):.2f} MB) to Supabase Storage: {bucket_name}/{dest_name}...")

    mime_type, _ = mimetypes.guess_type(str(path))
    content_type = mime_type or "video/mp4"

    try:
        with open(local_file_path, "rb") as f:
            file_bytes = f.read()

        # Upload or overwrite
        res = supabase.storage.from_(bucket_name).upload(
            dest_name,
            file_bytes,
            file_options={"content-type": content_type, "upsert": "true"},
        )

        # Retrieve public URL
        public_url = supabase.storage.from_(bucket_name).get_public_url(dest_name)
        print(f"✅ Supabase Storage upload complete!")
        print(f"   Streaming URL: {public_url}")
        return True, public_url

    except Exception as exc:
        err_msg = f"Supabase Storage upload failed: {exc}"
        print(f"❌ {err_msg}")
        return False, err_msg


def save_video_metadata_to_db(
    video_url: str,
    title: str,
    duration_seconds: float,
    headline_count: int,
    headlines_summary: Optional[list] = None,
    drive_url: Optional[str] = None,
) -> bool:
    """Save generated video metadata to Supabase table for news_web to query dynamically."""
    table_name = "generated_news_videos"
    data = {
        "title": title,
        "video_url": video_url,
        "duration_seconds": round(duration_seconds, 1),
        "headline_count": headline_count,
        "headlines_data": headlines_summary or [],
        "drive_url": drive_url or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table(table_name).insert(data).execute()
        print(f"✅ Video metadata recorded in Supabase table '{table_name}'.")
        return True
    except Exception as exc:
        # Table might not exist yet in Supabase schema
        print(f"ℹ️ Could not insert record into '{table_name}' ({exc}). Public URL remains directly accessible.")
        return False


# =====================================================================
# GOOGLE DRIVE INTEGRATION
# =====================================================================

def upload_to_google_drive(
    local_file_path: str,
    folder_id_or_link: Optional[str] = None,
    credentials_path: Optional[str] = None,
    destination_name: Optional[str] = None,
    supabase_url: Optional[str] = None,
) -> Tuple[bool, str]:
    """Upload video directly to Google Drive via Google Apps Script (GAS) or Drive API.

    Completely bypasses Supabase Storage to prevent exhausting database/bucket quotas.
    """
    path = Path(local_file_path)
    if not path.exists():
        return False, f"File does not exist: {local_file_path}"

    target_folder = folder_id_or_link or os.getenv("GDRIVE_FOLDER_ID", "").strip()

    # Clean folder ID if full drive link is passed
    folder_id = target_folder
    if "drive.google.com" in folder_id:
        if "folders/" in folder_id:
            folder_id = folder_id.split("folders/")[1].split("?")[0].strip()
        elif "id=" in folder_id:
            folder_id = folder_id.split("id=")[1].split("&")[0].strip()

    dest_filename = destination_name or path.name
    file_size_mb = path.stat().st_size / (1024 * 1024)

    # Method 1: Direct Google Apps Script (GAS) Upload (Zero credentials, zero Supabase)
    apps_script_url = os.getenv("GDRIVE_APPS_SCRIPT_URL", "").strip()
    if apps_script_url:
        try:
            print(f"🚀 [Google Drive] Direct upload via Google Apps Script ({file_size_mb:.2f} MB) -> {dest_filename}...")
            import base64
            import requests

            with open(local_file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

            payload = {
                "action": "upload_direct",
                "filename": dest_filename,
                "folder_id": folder_id,
                "file_base64": b64_data,
                "video_url": supabase_url or "",
            }

            headers = {"Content-Type": "application/json"}
            res = requests.post(apps_script_url, json=payload, headers=headers, timeout=180, allow_redirects=True)

            if res.status_code == 200 and "accounts.google.com" not in res.text:
                print(f"✅ Successfully uploaded {dest_filename} ({file_size_mb:.2f} MB) directly to Google Drive via GAS!")
                return True, target_folder
            elif "accounts.google.com" in res.text or res.status_code == 401:
                print("ℹ️ [Google Apps Script] Web app needs 'Who has access' set to 'Anyone' in deployment settings.")
            else:
                print(f"⚠️ [Google Apps Script] Response ({res.status_code}): {res.text[:250]}")
        except Exception as e:
            print(f"⚠️ Google Apps Script direct upload error: {e}")

    # Check for credentials
    cred_file = credentials_path or os.getenv("GDRIVE_CREDENTIALS_FILE", "credentials.json")

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2 import service_account

        creds = None
        token_file = Path(cred_file).parent / "token.json"

        # Check for cached OAuth token first
        if token_file.exists():
            try:
                from google.oauth2.credentials import Credentials
                creds = Credentials.from_authorized_user_file(
                    str(token_file), scopes=["https://www.googleapis.com/auth/drive"]
                )
            except Exception as e:
                print(f"⚠️ Could not load cached token.json: {e}")

        # Check for service account or client secret credentials
        if not creds and os.path.exists(cred_file):
            with open(cred_file, "r", encoding="utf-8") as f:
                cred_data = json.load(f)

            if cred_data.get("type") == "service_account":
                creds = service_account.Credentials.from_service_account_file(
                    cred_file, scopes=["https://www.googleapis.com/auth/drive"]
                )
            elif "installed" in cred_data or "web" in cred_data:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(
                    cred_file, scopes=["https://www.googleapis.com/auth/drive"]
                )
                creds = flow.run_local_server(port=0)
                with open(token_file, "w", encoding="utf-8") as t:
                    t.write(creds.to_json())

        if creds:
            service = build("drive", "v3", credentials=creds)

            file_metadata = {"name": path.name}
            if folder_id:
                file_metadata["parents"] = [folder_id]

            media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)
            uploaded_file = (
                service.files()
                .create(body=file_metadata, media_body=media, fields="id, webViewLink")
                .execute()
            )

            file_id = uploaded_file.get("id")
            web_link = uploaded_file.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
            print(f"✅ Google Drive upload complete! Link: {web_link}")
            return True, web_link
        else:
            msg = (
                f"Google Drive credentials file '{cred_file}' not found.\n"
                f"To enable direct automated upload to Google Drive, place your service account or OAuth 'credentials.json' "
                f"in the project folder or specify GDRIVE_CREDENTIALS_FILE in .env."
            )
            print(f"ℹ️ [Google Drive] {msg}")
            return False, msg

    except ImportError:
        msg = (
            "google-api-python-client is not yet installed in this venv. "
            "To enable automated Drive uploads: pip install google-api-python-client google-auth."
        )
        print(f"ℹ️ [Google Drive] {msg}")
        return False, msg
    except Exception as exc:
        err_msg = f"Google Drive upload encountered an error: {exc}"
        print(f"❌ {err_msg}")
        return False, err_msg


if __name__ == "__main__":
    print("Video Storage Manager module ready.")
