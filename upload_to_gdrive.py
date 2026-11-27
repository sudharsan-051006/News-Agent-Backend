"""Manual & Automated Google Drive Uploader for News Bulletins.

Usage:
    python upload_to_gdrive.py [video_path]
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents.video_storage import upload_to_google_drive

def main():
    folder_id = os.getenv("GDRIVE_FOLDER_ID", "https://drive.google.com/drive/folders/1jFFXoO2sqdDh3lpTcu40lRFTJmygIRRU?usp=sharing")

    # Target video
    if len(sys.argv) > 1:
        target_video = sys.argv[1]
    else:
        # Default to the latest generated bulletin
        outputs_dir = ROOT_DIR / "outputs"
        candidates = list(outputs_dir.glob("top25_bulletin_*.mp4")) + list(outputs_dir.glob("trending*.mp4"))
        if not candidates:
            print("❌ No generated bulletin videos found in outputs/ directory.")
            return
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        target_video = str(candidates[0])

    print(f"🎬 Target Video: {target_video} ({os.path.getsize(target_video)/(1024*1024):.2f} MB)")
    print(f"📁 Target Google Drive: {folder_id}")

    supabase_base = "https://atonkzxonfemlctmtdvo.supabase.co/storage/v1/object/public/news_videos"
    dest_name = "trending_headlines_latest.mp4" if "trending" in Path(target_video).name.lower() else "top25_headlines_latest.mp4"
    supabase_url = f"{supabase_base}/{dest_name}"

    success, link_or_msg = upload_to_google_drive(target_video, folder_id_or_link=folder_id, supabase_url=supabase_url)
    if success:
        print(f"\n🎉 Successfully uploaded to Google Drive!")
        print(f"🔗 File Link: {link_or_msg}")
    else:
        print(f"\n❌ Upload could not complete:")
        print(link_or_msg)

if __name__ == "__main__":
    main()
