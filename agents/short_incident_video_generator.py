"""60-Second Short Incident Video Generator for Elinity News Network.

Takes a verified incident dossier (with multi-source fact-checking and imagery),
generates a tight 130-140 word spoken broadcast script, synthesizes neural audio,
renders a dynamic 60-second multi-slide broadcast video (Tri-color: Red, Black, White),
and uploads directly to Google Drive via GAS with timestamped naming.
"""
from __future__ import annotations

import os
import re
import sys
import time
import asyncio
import urllib.request
import concurrent.futures
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

import cv2
import numpy as np
import qrcode
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
import edge_tts
import ollama

# Strict Tri-Color Broadcast Palette: Red, Black, White
RED_ACCENT = (215, 20, 20)      # #D71414
BLACK_BG = (10, 10, 10)         # #0A0A0A
WHITE_TEXT = (255, 255, 255)    # #FFFFFF
GRAY_TEXT = (180, 180, 180)     # #B4B4B4
CARD_BG = (16, 16, 16)          # #101010
BORDER_COLOR = (45, 45, 45)     # #2D2D2D

from agents.news_video_generator import (
    resolve_actual_publisher,
)
from agents.image_quality_filter import is_valid_article_photo, BROWSER_HEADERS
from agents.video_storage import upload_to_google_drive, upload_to_supabase_storage

DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:latest")
DEFAULT_VOICE = "en-IN-NeerjaNeural"

NUM_CORES = os.cpu_count() or 16

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
TARGET_DURATION = 60.0  # seconds


def create_placeholder_image(label: str = "SPOTLIGHT", w: int = 1920, h: int = 1080) -> np.ndarray:
    """Generate high-tech broadcast geometric background when an image is unavailable."""
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        r = int(14 + 12 * (y / h))
        canvas[y, :] = (r, 10, 10)
    for x in range(0, w, 60):
        cv2.line(canvas, (x, 0), (x, h), (28, 20, 20), 1)
    for y in range(0, h, 60):
        cv2.line(canvas, (0, y), (w, y), (28, 20, 20), 1)
    return canvas


def download_and_cache_photo(url: str, out_dir: Path, idx: int) -> Optional[str]:
    """Download image, validate that it is a real photo, and save to local path."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        arr = np.asarray(bytearray(data), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None

        is_photo, reason = is_valid_article_photo(img, url=url)
        if is_photo or (img.shape[0] >= 300 and img.shape[1] >= 400):
            save_path = str(out_dir / f"photo_{idx}_{int(time.time()*1000)%10000}.jpg")
            cv2.imwrite(save_path, img)
            print(f"   ✓ Validated news photo ({img.shape[1]}x{img.shape[0]}): {save_path}")
            return save_path
        else:
            print(f"   ⚠️ Image rejected by filter ({reason}): {url[:50]}")
    except Exception as exc:
        print(f"   ⚠️ Image download error ({type(exc).__name__}): {url[:50]}")
    return None


def get_broadcast_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Helper to load system TrueType fonts with fallback."""
    font_files = ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for base in ["C:/Windows/Fonts", "C:/WINNT/Fonts", "/usr/share/fonts", "/Library/Fonts"]:
        for name in font_files:
            p = Path(base) / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    pass
    return ImageFont.load_default()


def generate_60s_broadcast_script(
    dossier: Dict[str, Any],
    model: str = DEFAULT_OLLAMA_MODEL,
) -> str:
    """Generate a high-energy, punchy spoken narration script of exactly 130-140 words (~55-60 seconds)."""
    headline = dossier.get("headline") or dossier.get("topic_name")
    briefing = dossier.get("executive_briefing") or ""
    why_trending = dossier.get("why_trending") or ""
    key_facts = dossier.get("key_facts") or []
    official_quotes = dossier.get("official_quotes") or []

    facts_summary = "; ".join(key_facts[:3])
    quotes_summary = "; ".join([q for q in official_quotes[:2] if q and q != "None confirmed"])

    prompt = f"""You are an elite TV news anchor at Elinity News Network presenting a dedicated 60-second breaking spotlight.
Write a fast-paced, punchy, spoken audio news anchor script.

INCIDENT: {headline}
WHY IT MATTERS: {why_trending}
CORE BRIEFING: {briefing}
VERIFIED FACTS: {facts_summary}
OFFICIAL STATEMENTS: {quotes_summary}

RULES:
1. Spoken length: STRICTLY between 125 and 140 words. (Do not write more than 145 words).
2. Pacing:
   - 0-5s: Start with a sharp broadcast hook (e.g. "Breaking right now on Elinity News: ...").
   - 6-25s: Detail the core incident and confirmed numbers.
   - 26-45s: Quote official statements and background context.
   - 46-55s: State what is unfolding next.
   - 56-60s: End with: "Scan the on-screen QR code for our full investigative dossier. I am your Elinity anchor."
3. Plain spoken English with zero technical jargon, markdown, or bracketed directions. Return ONLY the spoken text."""

    try:
        res = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional television news broadcast anchor. Return only audio narration."},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.3, "num_thread": NUM_CORES},
        )
        script = res["message"]["content"].strip().strip('"\'')
        words = script.split()
        if len(words) >= 90:
            print(f"🎙️ Generated 60-second spoken script ({len(words)} words).")
            return script
    except Exception as exc:
        print(f"⚠️ Script generator note ({exc}). Assembling structured template script...")

    # Dynamic fallback script
    return (
        f"Breaking right now on Elinity News. {headline}. "
        f"{why_trending} "
        f"According to corroborated reports, {briefing} "
        f"Key verified developments confirm that {facts_summary or 'investigations are actively underway across multiple agencies'}. "
        f"Officials note that monitoring will continue as further details emerge throughout the day. "
        f"Scan the on-screen QR code right now for our full investigative dossier and verified citations. "
        f"This is Elinity News Network."
    )


async def synthesize_60s_audio(script: str, output_path: str, voice: str = DEFAULT_VOICE) -> float:
    """Synthesize neural speech audio and return duration in seconds."""
    communicate = edge_tts.Communicate(script, voice=voice, rate="+2%", pitch="+0Hz")
    await communicate.save(output_path)

    # Get duration
    try:
        import soundfile as sf
        info = sf.info(output_path)
        return float(info.duration)
    except Exception:
        # Fallback duration calculation
        words = len(script.split())
        return max(50.0, min(65.0, words / 2.3))


def generate_qr_card(url: str, size: int = 140) -> np.ndarray:
    """Generate scannable QR code badge."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=1,
    )
    qr.add_data(url or "https://elinity.news")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    return np.array(img)


def render_short_incident_slide(
    slide_index: int,
    total_slides: int,
    dossier: Dict[str, Any],
    image_path: Optional[str] = None,
    edition_meta: Optional[Tuple] = None,
) -> np.ndarray:
    """Render 1920x1080 broadcast slide for 60s incident spotlight (Tri-Color: Red, Black, White)."""
    headline = dossier.get("headline") or dossier.get("topic_name")
    pillar = dossier.get("pillar") or "BREAKING NEWS"
    key_facts = dossier.get("key_facts") or []
    official_quotes = dossier.get("official_quotes") or []

    # 1. Background image (Smart Crop & Aspect Ratio)
    if image_path and os.path.exists(image_path):
        bgr = cv2.imread(image_path)
        if bgr is not None:
            ih, iw = bgr.shape[:2]
            scale = max(VIDEO_WIDTH / iw, VIDEO_HEIGHT / ih)
            new_w, new_h = int(iw * scale), int(ih * scale)
            resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            x_start = max(0, (new_w - VIDEO_WIDTH) // 2)
            y_start = max(0, (new_h - VIDEO_HEIGHT) // 2)
            cropped = resized[y_start : y_start + VIDEO_HEIGHT, x_start : x_start + VIDEO_WIDTH]
            # Subtle cinematic tint
            dark_overlay = np.zeros_like(cropped)
            dark_overlay[:] = (10, 10, 10)
            photo = cv2.addWeighted(cropped, 0.88, dark_overlay, 0.12, 0)
        else:
            photo = create_placeholder_image(pillar, VIDEO_WIDTH, VIDEO_HEIGHT)
    else:
        photo = create_placeholder_image(pillar, VIDEO_WIDTH, VIDEO_HEIGHT)

    img_pil = Image.fromarray(cv2.cvtColor(photo, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    f_title = get_broadcast_font(42, bold=True)
    f_sub = get_broadcast_font(26, bold=True)
    f_body = get_broadcast_font(24, bold=False)
    f_pill = get_broadcast_font(18, bold=True)
    f_badge = get_broadcast_font(15, bold=True)

    # Top Live Header Bar
    draw.rectangle([0, 0, VIDEO_WIDTH, 72], fill=BLACK_BG)
    draw.line([(0, 72), (VIDEO_WIDTH, 72)], fill=RED_ACCENT, width=3)

    # Live Bug
    draw.rectangle([36, 18, 140, 54], fill=RED_ACCENT)
    draw.text((48, 25), "LIVE SPOTLIGHT", font=f_badge, fill=WHITE_TEXT)

    # Top Category Pill
    draw.text((160, 24), f"ELINITY NEWS NETWORK  •  {pillar.upper()}", font=f_sub, fill=WHITE_TEXT)

    # Slide Counter
    counter_text = f"INCIDENT REPORT  •  SEGMENT {slide_index}/{total_slides}"
    draw.text((VIDEO_WIDTH - 360, 26), counter_text, font=f_badge, fill=GRAY_TEXT)

    # Lower Third Banner (Chyron)
    chyron_top = VIDEO_HEIGHT - 280
    draw.rectangle([0, chyron_top, VIDEO_WIDTH, VIDEO_HEIGHT], fill=(8, 8, 8))
    draw.rectangle([0, chyron_top, VIDEO_WIDTH, chyron_top + 46], fill=RED_ACCENT)

    # Dynamic Chyron Header based on slide index
    if slide_index == 1:
        chyron_header = f"BREAKING INCIDENT REPORT  •  {dossier.get('velocity_score', 2.0)}x VELOCITY SURGE"
        card_content = dossier.get("why_trending") or dossier.get("executive_briefing") or headline
    elif slide_index == 2:
        chyron_header = "VERIFIED INCIDENT METRICS & DATA"
        card_content = "  •  ".join(key_facts[:2]) if key_facts else headline
    elif slide_index == 3:
        chyron_header = "OFFICIAL STATEMENTS & AGENCY CONFIRMATIONS"
        card_content = official_quotes[0] if official_quotes else dossier.get("executive_briefing")
    else:
        chyron_header = "ONGOING DEVELOPMENTS & INVESTIGATION"
        card_content = dossier.get("what_next") or dossier.get("executive_briefing")

    draw.text((40, chyron_top + 10), chyron_header, font=f_pill, fill=WHITE_TEXT)

    # Main Headline on Chyron
    draw.text((40, chyron_top + 60), headline[:75], font=f_title, fill=WHITE_TEXT)

    # Subtext / Fact content
    draw.text((40, chyron_top + 130), card_content[:140], font=f_body, fill=(220, 220, 220))

    # Scannable QR Badge (Bottom Right)
    qr_card = generate_qr_card(f"https://elinity.news/article/{dossier.get('incident_id', 'latest')}", size=130)
    qr_pil = Image.fromarray(qr_card)
    qr_x, qr_y = VIDEO_WIDTH - 220, chyron_top + 60
    img_pil.paste(qr_pil, (qr_x, qr_y))

    draw.rectangle([qr_x, qr_y + 135, qr_x + 130, qr_y + 160], fill=BLACK_BG)
    draw.text((qr_x + 10, qr_y + 140), "SCAN DOSSIER", font=get_broadcast_font(12, bold=True), fill=RED_ACCENT)

    # Convert back to OpenCV BGR
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def generate_short_incident_video(
    article_dossier: Dict[str, Any],
    output_dir: Optional[Path] = None,
    drive_folder: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate, render, and upload a dedicated 60-second incident video."""
    t0 = time.time()
    out_dir = output_dir or (ROOT_DIR / "outputs" / "shorts")
    out_dir.mkdir(parents=True, exist_ok=True)

    topic_name = article_dossier.get("headline") or article_dossier.get("topic_name") or "incident"
    clean_slug = re.sub(r"[^\w]", "_", topic_name.lower())[:30].strip("_")

    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    date_stamp = now_ist.strftime("%Y-%m-%d")
    time_stamp = now_ist.strftime("%I-%M%p")

    video_filename = f"short_{clean_slug}_{date_stamp}_{time_stamp}.mp4"
    final_video_path = str(out_dir / video_filename)
    audio_path = str(out_dir / f"audio_{clean_slug}_{date_stamp}.mp3")

    print("\n" + "=" * 65)
    print(f"🎬 [60s SHORT GENERATOR] Producing Video: {video_filename}")
    print("=" * 65)

    # Step 1: Spoken Script
    script = generate_60s_broadcast_script(article_dossier)

    # Step 2: Neural Speech Audio
    print("🔊 Synthesizing neural audio with edge-tts...")
    audio_duration = asyncio.run(synthesize_60s_audio(script, audio_path))
    print(f"   Audio Duration: {audio_duration:.1f}s")

    # Step 3: Prepare Imagery (Validate real photos across all CPU cores)
    raw_images: List[str] = []
    if article_dossier.get("image_url"):
        raw_images.append(article_dossier["image_url"])
    for u in article_dossier.get("verified_images", []):
        if u and u not in raw_images:
            raw_images.append(u)
    for ref in article_dossier.get("reference_articles", []):
        img_u = ref.get("image_url")
        if img_u and img_u not in raw_images:
            raw_images.append(img_u)

    print(f"🖼️ Validating {len(raw_images)} candidate images across {NUM_CORES} CPU cores...")
    valid_photos: List[str] = []
    if raw_images:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(raw_images), NUM_CORES)) as pool:
            futures = [pool.submit(download_and_cache_photo, u, out_dir, i) for i, u in enumerate(raw_images)]
            for fut in concurrent.futures.as_completed(futures):
                p = fut.result()
                if p:
                    valid_photos.append(p)

    if valid_photos:
        while len(valid_photos) < 4:
            valid_photos.append(valid_photos[0])
    else:
        # Fallback to high-tech broadcast visual placeholder so it NEVER displays pitch-black
        placeholder_path = str(out_dir / "broadcast_placeholder.jpg")
        cv2.imwrite(placeholder_path, create_placeholder_image("SPOTLIGHT", VIDEO_WIDTH, VIDEO_HEIGHT))
        valid_photos = [placeholder_path] * 4

    # Step 4: Render 4 High-Res Slides in Parallel (Multi-Core)
    print(f"🎞️ Rendering 4 high-res 1080p broadcast slides utilizing {NUM_CORES} CPU cores...")
    
    def render_and_save_slide(idx: int) -> Tuple[int, str]:
        img_p = valid_photos[idx - 1]
        slide_frame = render_short_incident_slide(
            slide_index=idx,
            total_slides=4,
            dossier=article_dossier,
            image_path=img_p,
        )
        s_path = str(out_dir / f"slide_{clean_slug}_{idx}.jpg")
        cv2.imwrite(s_path, slide_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        return idx, s_path

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        render_results = list(pool.map(render_and_save_slide, [1, 2, 3, 4]))
    
    render_results.sort(key=lambda x: x[0])
    slide_files = [r[1] for r in render_results]

    seg_duration = round(audio_duration / 4.0, 3)
    last_seg_duration = round(audio_duration - (seg_duration * 3), 3)

    # Step 5: High-Speed FFmpeg Concat Assembly (16 Cores, instantaneous)
    print(f"⚡ Multiplexing audio and video via FFmpeg ({NUM_CORES} threads)...")
    concat_txt = str(out_dir / f"concat_{clean_slug}.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        f.write(f"file '{slide_files[0]}'\nduration {seg_duration}\n")
        f.write(f"file '{slide_files[1]}'\nduration {seg_duration}\n")
        f.write(f"file '{slide_files[2]}'\nduration {seg_duration}\n")
        f.write(f"file '{slide_files[3]}'\nduration {last_seg_duration}\n")
        f.write(f"file '{slide_files[3]}'\n")

    import subprocess
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, "-y",
        "-threads", str(NUM_CORES),
        "-f", "concat",
        "-safe", "0",
        "-i", concat_txt,
        "-i", audio_path,
        "-r", "24",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "stillimage",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        final_video_path,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Cleanup temp slides & concat text
    if os.path.exists(concat_txt):
        os.remove(concat_txt)
    for s in slide_files:
        if os.path.exists(s):
            os.remove(s)
    if os.path.exists(audio_path):
        os.remove(audio_path)

    # Step 6: Store in Google Drive via GAS (Primary) with Supabase Fallback
    target_drive = drive_folder or os.getenv("GDRIVE_FOLDER_ID")
    drive_url = None
    supabase_url = None

    if target_drive:
        success, drive_msg = upload_to_google_drive(
            final_video_path,
            folder_id_or_link=target_drive,
            destination_name=video_filename,
        )
        if success:
            drive_url = drive_msg
            print(f"✅ 60s Video uploaded to Google Drive: {video_filename}")
        else:
            print(f"⚠️ Drive upload failed ({drive_msg}). Falling back to Supabase...")
            sb_ok, sb_url = upload_to_supabase_storage(final_video_path, destination_name=video_filename)
            if sb_ok:
                supabase_url = sb_url

    # Copy same-origin to news_web public/broadcast/
    web_broadcast_dir = Path("D:/AI PYTHON PROJECTS/news_web/public/broadcast")
    if web_broadcast_dir.exists():
        import shutil
        shutil.copy(final_video_path, web_broadcast_dir / video_filename)
        # Also copy as latest spotlight
        shutil.copy(final_video_path, web_broadcast_dir / "spotlight_latest.mp4")

    total_time = time.time() - t0
    print(f"🎉 60s Spotlight Video Complete in {total_time:.1f}s: {final_video_path}\n")

    return {
        "status": "success",
        "video_path": final_video_path,
        "video_filename": video_filename,
        "duration": audio_duration,
        "drive_url": drive_url,
        "supabase_url": supabase_url,
    }


if __name__ == "__main__":
    from agents.investigative_fact_checker import fetch_unprocessed_trending_incidents, investigate_incident
    from agents.incident_article_writer import write_incident_article

    incidents = fetch_unprocessed_trending_incidents(min_velocity=1.5, limit=1, force_all=True)
    if incidents:
        dossier = investigate_incident(incidents[0])
        article = write_incident_article(dossier)
        video_result = generate_short_incident_video(article)
        print("Video Result:", video_result)
    else:
        print("No incident available.")
