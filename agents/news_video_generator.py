"""News Video Generator Agent for News-Agent-Backend.

Assembles curated top headlines, their images, and synchronized audio narration
into a broadcast-quality TV news bulletin video (1280x720, 25fps) featuring:
- Dynamic Intro Card with date, time-of-day greeting (Namaste), and edition
- Dynamic Outro Card with closing note
- High-res typography (Segoe UI / Arial)
- On-screen article links and scannable QR codes for each news story
- Exported interactive timeline JSON and WebVTT cue chapters for news_web
- Web-optimized H.264/AAC with faststart streaming header
"""
from __future__ import annotations

import os
import sys
import math
import json
import hashlib
import urllib.request
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import cv2
import qrcode
import numpy as np
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

KNOWN_PUBLISHERS = {
    "news.un.org": "UN NEWS",
    "un.org": "UN NEWS",
    "thehindu.com": "THE HINDU",
    "sportstar.thehindu.com": "SPORTSTAR",
    "theverge.com": "THE VERGE",
    "bbc.com": "BBC NEWS",
    "bbc.co.uk": "BBC NEWS",
    "reuters.com": "REUTERS",
    "aljazeera.com": "AL JAZEERA",
    "indiatoday.in": "INDIA TODAY",
    "indiatimes.com": "TIMES OF INDIA",
    "timesofindia.indiatimes.com": "TIMES OF INDIA",
    "ndtv.com": "NDTV",
    "arstechnica.com": "ARS TECHNICA",
    "techcrunch.com": "TECHCRUNCH",
    "variety.com": "VARIETY",
    "hollywoodreporter.com": "HOLLYWOOD REPORTER",
    "espncricinfo.com": "ESPN CRICINFO",
    "espn.com": "ESPN",
    "indianexpress.com": "INDIAN EXPRESS",
    "moneycontrol.com": "MONEYCONTROL",
    "economictimes.indiatimes.com": "ECONOMIC TIMES",
    "bloomberg.com": "BLOOMBERG",
    "cnn.com": "CNN",
    "theguardian.com": "THE GUARDIAN",
    "apnews.com": "ASSOCIATED PRESS",
    "deccanherald.com": "DECCAN HERALD",
    "livemint.com": "MINT",
    "telegraphindia.com": "TELEGRAPH INDIA",
    "firstpost.com": "FIRSTPOST",
    "hindustantimes.com": "HINDUSTAN TIMES",
}


def resolve_actual_publisher(source: Optional[str], link: Optional[str]) -> Optional[str]:
    """Resolve legitimate news publisher channel name, completely omitting generic 'RSS'."""
    src = (source or "").strip()
    # If source is literally RSS, feed, xml, or generic placeholder, discard it
    if src.upper() in ["RSS", "FEED", "NEWS NETWORK", "UNKNOWN", "XML", "DEFAULT", ""]:
        src = ""

    if src:
        clean = src.split("/")[-1].replace(".xml", "").replace(".rss", "").strip().upper()
        if clean not in ["RSS", "FEED", "XML", ""]:
            return clean

    # Fallback to domain name from link
    if link and link.startswith("http"):
        try:
            netloc = urlparse(link).netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            if netloc in KNOWN_PUBLISHERS:
                return KNOWN_PUBLISHERS[netloc]
            for domain_pattern, pub_name in KNOWN_PUBLISHERS.items():
                if domain_pattern in netloc:
                    return pub_name
            # Fallback to clean primary domain name
            parts = netloc.split(".")
            if len(parts) >= 2:
                candidate = parts[-2].upper()
                if candidate not in ["COM", "ORG", "NET", "CO", "RSS", "FEED"]:
                    return candidate
        except Exception:
            pass

    return None

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# Category Theme Color Palette (RGB) - Strict Red, Black, and White Broadcast Theme
CATEGORY_COLORS = {
    "TECH": ((215, 20, 20), (25, 5, 5)),
    "GEOPOLITICS": ((215, 20, 20), (25, 5, 5)),
    "SPORTS": ((215, 20, 20), (25, 5, 5)),
    "MOVIES": ((215, 20, 20), (25, 5, 5)),
    "LOCAL": ((215, 20, 20), (25, 5, 5)),
    "GENERAL": ((215, 20, 20), (25, 5, 5)),
    "INDIA AFFAIRS": ((215, 20, 20), (25, 5, 5)),
}

# Fonts loader helper
def _get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for base in ["C:/Windows/Fonts", "C:/WINNT/Fonts", "/usr/share/fonts", "/Library/Fonts"]:
        p = Path(base) / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


def get_current_ist_meta() -> Tuple[str, str, str, str, str]:
    """Get current India Standard Time (IST) metadata: (greeting, edition, day_name, date_str, time_str)."""
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)

    hour = now.hour
    if 5 <= hour < 12:
        greeting = "good morning"
        edition = "MORNING EDITION"
    elif 12 <= hour < 17:
        greeting = "good afternoon"
        edition = "AFTERNOON EDITION"
    else:
        greeting = "good evening"
        edition = "EVENING EDITION"

    day_name = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")
    time_str = now.strftime("%I:%M %p IST")
    period_greeting = greeting.split()[-1]

    return greeting, edition, day_name, date_str, time_str


def create_dynamic_intro_card(edition: str, date_str: str, time_str: str, is_trending: bool = False, w: int = 1280, h: int = 720) -> np.ndarray:
    """Create a high-impact Red/Black/White broadcast opener card."""
    font_title = _get_font("segoeuib.ttf", 44)
    font_sub = _get_font("segoeuib.ttf", 26)
    font_bar = _get_font("segoeuib.ttf", 20)

    img = np.zeros((h, w, 3), dtype=np.uint8)
    cy, cx = h // 2, w // 2

    # Radial gradient backdrop (Red center glow fading into deep pure black)
    y_idx, x_idx = np.ogrid[:h, :w]
    dist = np.sqrt((x_idx - cx)**2 + (y_idx - cy)**2)
    max_d = np.sqrt(cx**2 + cy**2)
    factor = np.clip(1.0 - dist / max_d, 0, 1)

    # Red tint in center (BGR: Red is channel 2)
    img[..., 0] = (5 + 10 * factor).astype(np.uint8)   # Blue
    img[..., 1] = (5 + 10 * factor).astype(np.uint8)   # Green
    img[..., 2] = (15 + 65 * factor).astype(np.uint8)  # Red

    # Dark charcoal grid lines
    for x in range(0, w, 40):
        cv2.line(img, (x, 0), (x, h), (30, 30, 30), 1)
    for y in range(0, h, 40):
        cv2.line(img, (0, y), (w, y), (30, 30, 30), 1)

    # Crimson concentric broadcast rings
    for r in range(120, 440, 50):
        cv2.circle(img, (cx, cy - 30), r, (15, 15, 180), 1, cv2.LINE_AA)

    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    # Top Live Red Badge
    draw.rectangle([cx - 240, 50, cx + 240, 95], fill=(215, 20, 20), outline=(255, 60, 60), width=2)
    badge_label = f"LIVE BROADCAST  *  {edition}" if not is_trending else f"TRENDING NOW  *  {edition}"
    draw.text((cx - 190, 60), badge_label, font=font_bar, fill=(255, 255, 255))

    # Main Title (White)
    draw.text((cx - 285, cy - 85), "ELINITY NEWS NETWORK", font=font_title, fill=(255, 255, 255))
    # Subtitle (Red)
    sub_title = "TOP 25 BREAKING HEADLINES" if not is_trending else "TOP TRENDING STORIES REPORT"
    draw.text((cx - 240, cy - 25), sub_title, font=font_sub, fill=(235, 30, 30))
    # Tagline (White)
    draw.text((cx - 190, cy + 18), "DAILY COMPREHENSIVE BRIEFING", font=font_bar, fill=(230, 230, 230))

    # Bottom Info Bar (Black container, Red outline, White text)
    draw.rectangle([60, h - 85, w - 60, h - 35], fill=(12, 12, 12), outline=(215, 20, 20), width=2)
    draw.text((85, h - 70), f"DATE: {date_str.upper()}   |   TIME: {time_str}   |   DAILY COMPREHENSIVE EDITION", font=font_bar, fill=(240, 240, 240))

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def create_dynamic_outro_card(date_str: str, w: int = 1280, h: int = 720) -> np.ndarray:
    """Create a Red/Black/White broadcast sign-off card."""
    font_title = _get_font("segoeuib.ttf", 44)
    font_sub = _get_font("segoeuib.ttf", 26)
    font_bar = _get_font("segoeuib.ttf", 20)

    img = np.zeros((h, w, 3), dtype=np.uint8)
    cy, cx = h // 2, w // 2

    y_idx, x_idx = np.ogrid[:h, :w]
    dist = np.sqrt((x_idx - cx)**2 + (y_idx - cy)**2)
    max_d = np.sqrt(cx**2 + cy**2)
    factor = np.clip(1.0 - dist / max_d, 0, 1)

    img[..., 0] = (5 + 10 * factor).astype(np.uint8)
    img[..., 1] = (5 + 10 * factor).astype(np.uint8)
    img[..., 2] = (15 + 65 * factor).astype(np.uint8)

    for x in range(0, w, 40):
        cv2.line(img, (x, 0), (x, h), (30, 30, 30), 1)
    for y in range(0, h, 40):
        cv2.line(img, (0, y), (w, y), (30, 30, 30), 1)

    for r in range(120, 440, 50):
        cv2.circle(img, (cx, cy - 30), r, (15, 15, 180), 1, cv2.LINE_AA)

    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    # Top Badge (Red)
    draw.rectangle([cx - 240, 50, cx + 240, 95], fill=(215, 20, 20), outline=(255, 60, 60), width=2)
    draw.text((cx - 170, 60), "BULLETIN SIGN-OFF  *  NAMASTE", font=font_bar, fill=(255, 255, 255))

    # Main Sign-Off (White)
    draw.text((cx - 280, cy - 85), "BULLETIN COMPLETE", font=font_title, fill=(255, 255, 255))
    # Sub (Red)
    draw.text((cx - 250, cy - 25), "THANK YOU FOR WATCHING", font=font_sub, fill=(235, 30, 30))
    # Tag (White)
    draw.text((cx - 210, cy + 18), "STAY INFORMED  *  STAY SAFE", font=font_bar, fill=(230, 230, 230))

    # Bottom Info Bar (Black/Red/White)
    draw.rectangle([60, h - 85, w - 60, h - 35], fill=(12, 12, 12), outline=(215, 20, 20), width=2)
    draw.text((85, h - 70), f"ELINITY NEWS   |   {date_str.upper()}   |   DAILY COMPREHENSIVE EDITION", font=font_bar, fill=(240, 240, 240))

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def download_and_prepare_image(url: str, cache_path: str, target_w: int = 1280, target_h: int = 720) -> np.ndarray:
    """Download image or load from cache and format into a high-res 1280x720 frame."""
    path = Path(cache_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                with open(cache_path, "wb") as f:
                    f.write(data)
        except Exception as exc:
            print(f"⚠️ Image download failed for {url[:50]}: {exc}")
            return create_placeholder_image("News Image Update", target_w, target_h)

    img = cv2.imread(cache_path)
    if img is None:
        return create_placeholder_image("Broadcast Visual", target_w, target_h)
    return img


def create_placeholder_image(label: str, w: int = 1280, h: int = 720) -> np.ndarray:
    """Generate a clean high-tech news graphic placeholder when an image is unavailable."""
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    for x in range(0, w, 40):
        cv2.line(canvas, (x, 0), (x, h), (25, 35, 55), 1)
    for y in range(0, h, 40):
        cv2.line(canvas, (0, y), (w, y), (25, 35, 55), 1)

    pil_img = Image.fromarray(canvas)
    draw = ImageDraw.Draw(pil_img)
    font = _get_font("segoeuib.ttf", 28)
    draw.text((w // 2 - 150, h // 2 - 20), label, font=font, fill=(180, 210, 255))
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def apply_ken_burns(
    img: np.ndarray,
    progress: float,
    mode: int = 0,
    target_w: int = 1280,
    target_h: int = 720,
) -> np.ndarray:
    """Apply cinematic camera zoom and pan across the image."""
    ih, iw = img.shape[:2]

    if mode % 4 == 0:
        scale = 1.02 + 0.12 * progress
        off_x = 0.2 + 0.6 * progress
        off_y = 0.3
    elif mode % 4 == 1:
        scale = 1.15 - 0.12 * progress
        off_x = 0.5
        off_y = 0.2 + 0.5 * progress
    elif mode % 4 == 2:
        scale = 1.08
        off_x = 0.7 - 0.4 * progress
        off_y = 0.4
    else:
        scale = 1.08
        off_x = 0.3 + 0.4 * progress
        off_y = 0.3

    crop_w = int(iw / scale)
    crop_h = int(crop_w * (target_h / target_w))
    if crop_h > ih:
        crop_h = ih
        crop_w = int(crop_h * (target_w / target_h))

    max_x = max(0, iw - crop_w)
    max_y = max(0, ih - crop_h)
    x0 = int(max_x * np.clip(off_x, 0.0, 1.0))
    y0 = int(max_y * np.clip(off_y, 0.0, 1.0))

    crop = img[y0 : y0 + crop_h, x0 : x0 + crop_w]
    return cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_LINEAR)


def render_broadcast_overlay(
    frame_bgr: np.ndarray,
    headline_item: Dict[str, Any],
    frame_idx: int,
    total_headlines: int,
) -> np.ndarray:
    """Draw broadcast lower-thirds, top chyrons, scannable QR code, and live bug over the frame."""
    h, w = frame_bgr.shape[:2]
    pil_frame = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_frame)

    font_headline = _get_font("segoeuib.ttf", 23)
    font_chyron = _get_font("segoeuib.ttf", 18)
    font_sub = _get_font("arialbd.ttf", 14)
    font_small = _get_font("arial.ttf", 11)

    cat = headline_item.get("category", "GENERAL").upper()
    idx = headline_item.get("index", 1)
    title = headline_item.get("headline", "Breaking News")
    raw_source = headline_item.get("source", "")
    link = headline_item.get("link", "")
    is_trending = headline_item.get("is_trending", False)

    # Resolve actual news publisher channel name, completely stripping generic 'RSS'
    publisher = resolve_actual_publisher(raw_source, link)

    # 1. Top-Right Live Bug (Black/Red/White)
    draw.rectangle([1010, 28, 1245, 62], fill=(10, 10, 10), outline=(220, 20, 20), width=2)
    pulse = int(180 + 75 * math.sin(frame_idx * 0.25))
    draw.ellipse([1022, 40, 1032, 50], fill=(235, 25, 25, pulse))
    bug_text = "TRENDING  |  LIVE" if is_trending else "LIVE  |  BREAKING"
    draw.text((1042, 35), bug_text, font=font_chyron, fill=(255, 255, 255))

    # 2. Top-Left Category Chyron (Red/Black/White)
    draw.rectangle([40, 28, 520, 62], fill=(215, 20, 20))
    bulletin_header = f"TRENDING STORIES  |  #{idx:02d} OF {total_headlines:02d}" if is_trending else f"TOP 25 HEADLINES  |  #{idx:02d} OF {total_headlines:02d}"
    draw.text((55, 35), bulletin_header, font=font_chyron, fill=(255, 255, 255))
    draw.rectangle([40, 62, 520, 90], fill=(12, 12, 12), outline=(50, 50, 50), width=1)

    if publisher:
        chyron_sub = f"CATEGORY: {cat}  *  SOURCE: {publisher}"
    else:
        chyron_sub = f"CATEGORY: {cat}"
    draw.text((55, 66), chyron_sub, font=font_sub, fill=(230, 230, 230))

    # 3. High-Contrast Scannable QR Code Badge (Red/Black/White)
    if link and link.startswith("http"):
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=4,
                border=2,
            )
            qr.add_data(link)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            qr_resized = qr_img.resize((134, 134), Image.Resampling.LANCZOS)

            # Floating container (Jet black with crimson outline)
            draw.rectangle([1090, 410, 1255, 582], fill=(10, 10, 10), outline=(220, 20, 20), width=2)
            # Header (Red with White text)
            draw.rectangle([1092, 412, 1253, 438], fill=(190, 15, 15))
            draw.text((1118, 417), "SCAN ARTICLE", font=font_small, fill=(255, 255, 255))
            # Pure white card inside for 100% camera readability
            draw.rectangle([1103, 442, 1241, 580], fill=(255, 255, 255))
            pil_frame.paste(qr_resized, (1105, 444))
        except Exception:
            pass

    # 4. Lower-Third Breaking News Banner (Jet Black / Crimson Red / Pure White)
    draw.rectangle([0, 595, w, h], fill=(10, 10, 10))
    # Red accent horizontal line
    draw.line([(0, 595), (w, 595)], fill=(225, 20, 20), width=3)

    # Red Breaking News Badge on left
    draw.rectangle([0, 595, 200, h], fill=(215, 20, 20))
    badge_l1 = "TRENDING" if is_trending else "BREAKING"
    badge_l2 = "STORY" if is_trending else "NEWS"
    draw.text((35, 625), badge_l1, font=font_headline, fill=(255, 255, 255))
    draw.text((55, 658), badge_l2, font=font_headline, fill=(255, 255, 255))

    # Headline Text (Pure White)
    if len(title) > 65:
        line1 = title[:65].rsplit(" ", 1)[0]
        line2 = title[len(line1) :].strip()
        draw.text((225, 612), line1, font=font_headline, fill=(255, 255, 255))
        draw.text((225, 642), line2, font=font_headline, fill=(255, 255, 255))
    else:
        draw.text((225, 622), title, font=font_headline, fill=(255, 255, 255))

    # On-Screen Article Link (Pure White with Red accent separator)
    clean_url = link[:75] + ("..." if len(link) > 75 else "") if link else "elinitynews.com"
    if publisher:
        footer_sub = f"SOURCE: {publisher}   |   ARTICLE: {clean_url}"
    else:
        footer_sub = f"ARTICLE LINK: {clean_url}"
    draw.text((225, 680), footer_sub, font=font_sub, fill=(255, 255, 255))

    return cv2.cvtColor(np.array(pil_frame), cv2.COLOR_RGB2BGR)


def generate_headlines_video(
    headlines: List[Dict[str, Any]],
    output_video_path: str,
    intro_segment: Optional[Dict[str, Any]] = None,
    outro_segment: Optional[Dict[str, Any]] = None,
    cache_dir: str = "outputs/cache_images",
    fps: int = 25,
    transition_frames: int = 12,
    target_w: int = 1280,
    target_h: int = 720,
) -> Tuple[str, str, str]:
    """Render full broadcast bulletin video with dynamic intro, outro, article links, and timeline JSON.

    Returns:
        (video_file_path, timeline_json_path, webvtt_path)
    """
    total = len(headlines)
    if total == 0:
        raise ValueError("Cannot generate video with 0 headlines.")

    out_path = Path(output_video_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_video = str(out_path.parent / "temp_bulletin_visuals.mp4")
    concat_audio_list = str(out_path.parent / "audio_concat_list.txt")
    temp_master_audio = str(out_path.parent / "temp_bulletin_master_audio.mp3")
    timeline_prefix = "trending" if "trending" in out_path.stem else "headlines"
    timeline_json_path = str(out_path.parent / f"{timeline_prefix}_timeline.json")
    webvtt_path = str(out_path.parent / "bulletin_chapters.vtt")

    print(f"\n🎬 Starting broadcast video generation for {total} headlines + Intro/Outro...")

    # Step 1: Pre-download and prepare all article images (100% 1-to-1 match guaranteed)
    prepared_images = []
    for idx, item in enumerate(headlines, start=1):
        img_path = item.get("image_path")
        if img_path and os.path.exists(img_path):
            img_bgr = cv2.imread(img_path)
            if img_bgr is not None and img_bgr.size > 0:
                prepared_images.append(img_bgr)
                continue
        # Fallback to fresh download with unique URL hash
        url = item.get("image_url", "")
        url_hash = hashlib.md5((url or f"item_{idx}").encode()).hexdigest()[:8]
        img_cache = os.path.join(cache_dir, f"art_{idx:02d}_{url_hash}.jpg")
        img_bgr = download_and_prepare_image(url, img_cache, target_w, target_h)
        prepared_images.append(img_bgr)

    # Step 2: Build Audio Concatenation List
    all_segments = []
    if intro_segment:
        all_segments.append(intro_segment)
    all_segments.extend(headlines)
    if outro_segment:
        all_segments.append(outro_segment)

    with open(concat_audio_list, "w", encoding="utf-8") as f:
        for seg in all_segments:
            audio_p = Path(seg["audio_path"]).resolve()
            f.write(f"file '{str(audio_p).replace(chr(92), '/')}'\n")

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd_audio = [
        ff, "-y",
        "-threads", "0",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_audio_list,
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        temp_master_audio,
    ]
    subprocess.run(cmd_audio, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("✅ Master audio track concatenated successfully.")

    # Step 3: Render Video Frames
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(temp_video, fourcc, fps, (target_w, target_h))

    timeline_data = []
    total_rendered_frames = 0
    current_time_sec = 0.0

    # 3A: Render Intro Segment
    if intro_segment:
        dur = max(4.0, intro_segment.get("audio_duration", 6.0))
        seg_frames = int(dur * fps)
        intro_img = intro_segment.get("frame_image")
        start_t = current_time_sec
        end_t = current_time_sec + dur

        for sf in range(seg_frames):
            p = sf / float(seg_frames)
            scale = 1.0 + 0.04 * p
            crop_base = apply_ken_burns(intro_img, p, mode=0, target_w=target_w, target_h=target_h)
            writer.write(crop_base)
            total_rendered_frames += 1

        timeline_data.append({
            "segment": "INTRO",
            "title": "Welcome & Daily Briefing",
            "link": "",
            "start_time": round(start_t, 2),
            "end_time": round(end_t, 2),
        })
        current_time_sec = end_t
        print(f"  🌟 Rendered INTRO segment ({seg_frames} frames, {dur:.1f}s)")

    # 3B: Render 25 Headline Slides
    for idx in range(total):
        item = headlines[idx]
        cur_img = prepared_images[idx]
        dur = max(3.5, item.get("audio_duration", 4.5))
        slide_frames = int(dur * fps)
        mode = idx

        next_img = prepared_images[idx + 1] if idx + 1 < total else (outro_segment.get("frame_image") if outro_segment else None)
        start_t = current_time_sec
        end_t = current_time_sec + dur

        for sf in range(slide_frames):
            p = sf / float(slide_frames)
            frame_base = apply_ken_burns(cur_img, p, mode=mode, target_w=target_w, target_h=target_h)

            if next_img is not None and sf >= (slide_frames - transition_frames):
                trans_p = (sf - (slide_frames - transition_frames)) / float(transition_frames)
                next_base = apply_ken_burns(next_img, 0.0, mode=mode + 1, target_w=target_w, target_h=target_h)
                frame_base = cv2.addWeighted(frame_base, 1.0 - trans_p, next_base, trans_p, 0)

            final_frame = render_broadcast_overlay(frame_base, item, total_rendered_frames, total)
            writer.write(final_frame)
            total_rendered_frames += 1

        timeline_data.append({
            "segment": f"STORY #{idx+1:02d}",
            "index": idx + 1,
            "category": item.get("category"),
            "title": item.get("headline"),
            "link": item.get("link"),
            "source": item.get("source"),
            "start_time": round(start_t, 2),
            "end_time": round(end_t, 2),
        })
        current_time_sec = end_t
        print(f"  📽️ Rendered slide {idx+1:02d}/{total:02d} ({slide_frames} frames, {dur:.1f}s)")

    # 3C: Render Outro Segment
    if outro_segment:
        dur = max(4.0, outro_segment.get("audio_duration", 6.0))
        seg_frames = int(dur * fps)
        outro_img = outro_segment.get("frame_image")
        start_t = current_time_sec
        end_t = current_time_sec + dur

        for sf in range(seg_frames):
            p = sf / float(seg_frames)
            crop_base = apply_ken_burns(outro_img, p, mode=1, target_w=target_w, target_h=target_h)
            writer.write(crop_base)
            total_rendered_frames += 1

        timeline_data.append({
            "segment": "OUTRO",
            "title": "Bulletin Sign-Off & Closing Note",
            "link": "",
            "start_time": round(start_t, 2),
            "end_time": round(end_t, 2),
        })
        current_time_sec = end_t
        print(f"  🌟 Rendered OUTRO segment ({seg_frames} frames, {dur:.1f}s)")

    writer.release()
    print(f"✅ Video stream complete: {total_rendered_frames} frames ({total_rendered_frames/fps:.1f}s)")

    # Step 4: Write timeline JSON & WebVTT cue chapters
    with open(timeline_json_path, "w", encoding="utf-8") as f:
        json.dump(timeline_data, f, indent=2)
    print(f"📄 Saved clickable timeline JSON: {timeline_json_path}")

    # WebVTT
    with open(webvtt_path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for item in timeline_data:
            s_m, s_s = divmod(item["start_time"], 60)
            e_m, e_s = divmod(item["end_time"], 60)
            f.write(f"{int(s_m):02d}:{s_s:06.3f} --> {int(e_m):02d}:{e_s:06.3f}\n")
            f.write(f"{item['title']}\n")
            if item.get("link"):
                f.write(f"{item['link']}\n")
            f.write("\n")
    print(f"📄 Saved WebVTT chapter cues: {webvtt_path}")

    # Step 5: Final Audio-Video Muxing with H.264 / AAC and faststart
    print("📦 Muxing video and audio with faststart for web streaming...")
    cmd_mux = [
        ff, "-y",
        "-threads", "0",
        "-i", temp_video,
        "-i", temp_master_audio,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "24",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd_mux, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for tmp in [temp_video, temp_master_audio, concat_audio_list]:
        if os.path.exists(tmp):
            os.remove(tmp)

    print(f"\n🎉 BROADCAST BULLETIN VIDEO READY: {out_path}")
    print(f"   Size: {os.path.getsize(str(out_path)) / (1024*1024):.2f} MB")
    return str(out_path), timeline_json_path, webvtt_path


if __name__ == "__main__":
    print("News Video Generator ready.")
