"""Master Top 25 News Headlines Video Pipeline for News-Agent-Backend.

Connects:
1. Top 25 Headlines curation from Supabase across all channels and categories.
2. Varied broadcast connectors (no repetitive category prefixes).
3. Dynamic time-of-day greeting (Namaste, good morning/afternoon/evening) and date/edition intro.
4. Closing sign-off note (Outro).
5. On-screen article links and scannable QR codes for each headline.
6. Exported clickable timeline JSON for interactive news_web video player.
7. Dual-Engine Audio Narration (Sarvam AI API as primary with automatic offline fallback).
8. Storage pipeline (Google Drive upload + Supabase Storage CDN integration).
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents.top_headlines_selector import get_top_headlines
from agents.trending_headlines_selector import get_trending_headlines
from agents.audio_synthesizer import batch_synthesize_headlines, synthesize_speech
from agents.llm_script_writer import (
    generate_broadcast_intro,
    generate_broadcast_outro,
    batch_generate_scripts_with_llm,
)
from agents.news_video_generator import (
    generate_headlines_video,
    get_current_ist_meta,
    create_dynamic_intro_card,
    create_dynamic_outro_card,
)
from agents.video_storage import upload_to_supabase_storage, save_video_metadata_to_db, upload_to_google_drive


def run_pipeline(
    count: int = 25,
    mode: str = "top25",
    sarvam_api_key: str | None = None,
    drive_folder: str | None = None,
    output_path: str | None = None,
    upload_supabase: bool = True,
    offline_voice: str = "en-IN-NeerjaNeural",
    audio_engine: str = "model",
    from_scratch: bool = True,
) -> dict:
    start_time = time.time()
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    greeting, edition, day_name, date_str, time_str = get_current_ist_meta()
    period_greeting = greeting.split()[-1]
    is_trending_mode = mode.lower() == "trending"
    bulletin_type = "TRENDING STORIES" if is_trending_mode else "TOP HEADLINES"

    # Audio engine determination
    effective_sarvam_key = sarvam_api_key or os.getenv("SARVAM_API_KEY")
    if audio_engine.lower() in ("model", "offline"):
        effective_sarvam_key = None
        engine_label = f"Offline Neural Model ({offline_voice})"
    elif effective_sarvam_key:
        engine_label = f"Sarvam AI API (Primary) with Offline Neural Fallback ({offline_voice})"
    else:
        engine_label = f"Offline Neural Model ({offline_voice})"

    print("\n" + "=" * 65)
    print(f"      ELINITY NEWS AGENT: {bulletin_type} VIDEO PIPELINE")
    print("=" * 65)
    print(f"Mode:                  {bulletin_type}")
    print(f"Target Count:          {count}")
    print(f"Broadcast Edition:     {edition}")
    print(f"Broadcast Time:        {day_name}, {date_str} • {time_str}")
    print(f"Audio Engine:          {engine_label}")
    print(f"Script Generation:     Local LLM (mistral:latest via Ollama)")
    print(f"Generate From Scratch: {from_scratch}")
    print(f"Supabase CDN Upload:   {upload_supabase}")
    print(f"Google Drive Target:   {drive_folder or os.getenv('GDRIVE_FOLDER_ID', 'None')}")
    print("=" * 65 + "\n")

    output_dir = ROOT_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / f"audio_{timestamp_str}"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cache_img_dir = output_dir / "cache_images"
    verified_img_dir = output_dir / "verified_images"

    # If from scratch, purge stale caches to ensure 100% fresh 1-to-1 images
    if from_scratch:
        print("🧹 [SCRATCH MODE] Purging stale cached images and temporary artifacts...")
        for cdir in (cache_img_dir, verified_img_dir):
            if cdir.exists():
                for f in cdir.glob("*.*"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
        cache_img_dir.mkdir(parents=True, exist_ok=True)
        verified_img_dir.mkdir(parents=True, exist_ok=True)

    prefix = "trending" if is_trending_mode else "top"
    final_video = output_path or str(output_dir / f"{prefix}{count}_bulletin_{timestamp_str}.mp4")

    # -------------------------------------------------------------
    # Step 1: Select and Curate Headlines
    # -------------------------------------------------------------
    if is_trending_mode:
        print(f"[STAGE 1/4] Curating Top {count} Trending Stories from Neon Database...")
        t0 = time.time()
        headlines = get_trending_headlines(target_count=count, verify_images=True)
    else:
        print(f"[STAGE 1/4] Curating Top {count} Headlines from Supabase across categories...")
        t0 = time.time()
        headlines = get_top_headlines(target_count=count, verify_images=True)

    if not headlines:
        print("❌ Error: No headlines could be retrieved or verified.")
        return {"status": "failed", "error": "No headlines retrieved"}
    print(f"  -> Curated {len(headlines)} stories with verified photography in {time.time() - t0:.1f}s.\n")

    # -------------------------------------------------------------
    # Step 1.5: Dynamic LLM Anchor Narration Script Generation
    # -------------------------------------------------------------
    print("[STAGE 1.5] Crafting broadcast narration scripts using Local LLM...")
    headlines = batch_generate_scripts_with_llm(headlines)

    # -------------------------------------------------------------
    # Step 2: Dynamic Audio Narration Generation (Intro + Stories + Outro)
    # -------------------------------------------------------------
    print(f"[STAGE 2/4] Synthesizing audio narration ({engine_label})...")
    t0 = time.time()

    is_sarvam_requested = audio_engine.lower() == "sarvam"

    # 2A: Dynamic Intro Greeting via LLM
    intro_spoken_text = generate_broadcast_intro(
        day_name=day_name,
        date_str=date_str,
        time_str=time_str,
        edition=edition,
        total_count=len(headlines),
    )
    intro_audio_file = str(audio_dir / "intro_greeting.mp3")
    print(f"  🎙️ Synthesizing dynamic intro greeting ({edition})...")
    intro_engine, intro_dur = synthesize_speech(
        text=intro_spoken_text,
        output_path=intro_audio_file,
        sarvam_api_key=effective_sarvam_key,
        use_sarvam=is_sarvam_requested,
        offline_voice=offline_voice,
    )
    intro_img = create_dynamic_intro_card(edition=edition, date_str=date_str, time_str=time_str, is_trending=is_trending_mode)
    intro_segment = {
        "audio_path": intro_audio_file,
        "audio_duration": intro_dur,
        "frame_image": intro_img,
    }

    # 2B: Headline Stories Audio
    headlines = batch_synthesize_headlines(
        headlines=headlines,
        output_dir=str(audio_dir),
        sarvam_api_key=effective_sarvam_key,
        use_sarvam=is_sarvam_requested,
        offline_voice=offline_voice,
    )

    # 2C: Dynamic Outro Sign-Off via LLM
    outro_spoken_text = generate_broadcast_outro(
        day_name=day_name,
        date_str=date_str,
        total_count=len(headlines),
    )
    outro_audio_file = str(audio_dir / "outro_signoff.mp3")
    print(f"  🎙️ Synthesizing closing sign-off note...")
    outro_engine, outro_dur = synthesize_speech(
        text=outro_spoken_text,
        output_path=outro_audio_file,
        sarvam_api_key=effective_sarvam_key,
        use_sarvam=is_sarvam_requested,
        offline_voice=offline_voice,
    )
    outro_img = create_dynamic_outro_card(date_str=date_str)
    outro_segment = {
        "audio_path": outro_audio_file,
        "audio_duration": outro_dur,
        "frame_image": outro_img,
    }

    total_audio_duration = intro_dur + sum(h.get("audio_duration", 0) for h in headlines) + outro_dur
    print(f"  -> All audio tracks generated in {time.time() - t0:.1f}s. Total bulletin: {total_audio_duration/60:.1f} min.\n")

    # -------------------------------------------------------------
    # Step 3: Broadcast Video Generation with Ken Burns, Links & QR Codes
    # -------------------------------------------------------------
    print("[STAGE 3/4] Compositing broadcast video with intro, outro, article links & QR codes...")
    t0 = time.time()
    video_file, timeline_json, webvtt_file = generate_headlines_video(
        headlines=headlines,
        output_video_path=final_video,
        intro_segment=intro_segment,
        outro_segment=outro_segment,
        cache_dir=str(cache_img_dir),
    )
    print(f"  -> Video rendered and muxed in {time.time() - t0:.1f}s.\n")

    # -------------------------------------------------------------
    # Step 4: Storage & Distribution (Supabase CDN + Google Drive)
    # -------------------------------------------------------------
    print("[STAGE 4/4] Distributing and storing broadcast video...")
    supabase_url = None
    timeline_cdn_url = None
    drive_url = None

    # Format human-readable date and time for video naming (IST)
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    date_stamp = now_ist.strftime("%Y-%m-%d")
    time_stamp = now_ist.strftime("%I-%M%p")

    bulletin_prefix = "trending_headlines" if is_trending_mode else "top25_headlines"
    dest_filename = f"{bulletin_prefix}_{date_stamp}_{time_stamp}.mp4"
    timeline_dest = f"{bulletin_prefix}_{date_stamp}_{time_stamp}_timeline.json"
    latest_filename = f"{bulletin_prefix}_latest.mp4"

    # Step 1: Attempt Google Drive upload first (named with date and time)
    drive_upload_success = False
    if drive_folder:
        print(f"📁 [Storage] Primary Destination: Google Drive ({dest_filename})...")
        success, drive_url_or_msg = upload_to_google_drive(
            video_file, 
            folder_id_or_link=drive_folder, 
            destination_name=dest_filename, 
            supabase_url=None
        )
        if success:
            drive_upload_success = True
            drive_url = drive_url_or_msg
            print(f"✅ Video safely saved to Google Drive: {dest_filename}")
        else:
            print(f"⚠️ Google Drive upload failed or timed out: {drive_url_or_msg}")
            print(f"🔄 Automatic Fallback: Uploading video to Supabase Storage...")

    # Step 2: Upload to Supabase Storage ONLY if Google Drive failed, or if explicitly forced
    should_upload_supabase = (not drive_upload_success) or upload_supabase
    if should_upload_supabase:
        fallback_label = "fallback" if not drive_upload_success and drive_folder else "requested"
        print(f"📦 [Storage] Uploading to Supabase Storage ({fallback_label} destination: {dest_filename})...")
        success, url_or_err = upload_to_supabase_storage(video_file, destination_name=dest_filename)
        if success:
            supabase_url = url_or_err
            print(f"✅ Stored in Supabase: {supabase_url}")
        else:
            print(f"❌ Supabase Storage upload failed: {url_or_err}")

        # Also upload clickable timeline JSON to Supabase Storage for news_web
        if os.path.exists(timeline_json):
            success_json, json_url_or_err = upload_to_supabase_storage(
                timeline_json, destination_name=timeline_dest
            )
            if success_json:
                timeline_cdn_url = json_url_or_err

    # Record metadata in Supabase table for news_web
    if supabase_url:
        bulletin_title = f"Top {len(headlines)} Trending Stories Bulletin ({edition})" if is_trending_mode else f"Top {len(headlines)} Breaking News Bulletin ({edition})"
        save_video_metadata_to_db(
            video_url=supabase_url,
            title=bulletin_title,
            duration_seconds=total_audio_duration,
            headline_count=len(headlines),
            headlines_summary=[
                {
                    "index": h["index"],
                    "category": h["category"],
                    "headline": h["headline"],
                    "source": h["source"],
                    "link": h.get("link", ""),
                }
                for h in headlines
            ],
            drive_url=drive_url,
        )

    total_time = time.time() - start_time
    print("\n" + "=" * 65)
    print("🎉 PIPELINE EXECUTION COMPLETE")
    print("=" * 65)
    print(f"Total Execution Time:    {total_time:.1f}s ({total_time/60:.1f} min)")
    print(f"Local Video File:        {video_file}")
    print(f"Timeline JSON:           {timeline_json}")
    if supabase_url:
        print(f"Supabase Streaming CDN:  {supabase_url}")
    if timeline_cdn_url:
        print(f"Timeline Metadata CDN:   {timeline_cdn_url}")
    if drive_url:
        print(f"Google Drive Link:       {drive_url}")
    print("=" * 65 + "\n")

    return {
        "status": "success",
        "video_path": video_file,
        "timeline_json": timeline_json,
        "supabase_cdn_url": supabase_url,
        "drive_url": drive_url,
        "headline_count": len(headlines),
        "total_duration": total_audio_duration,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate Top News Headlines Broadcast Video")
    parser.add_argument("--count", type=int, default=25, help="Number of headlines to include (default: 25)")
    parser.add_argument("--mode", type=str, default="top25", choices=["top25", "trending"], help="Bulletin mode: top25 or trending")
    parser.add_argument("--sarvam-key", type=str, default=None, help="Sarvam AI API key")
    parser.add_argument("--drive-folder", type=str, default=None, help="Google Drive folder link or folder ID")
    parser.add_argument("--output", type=str, default=None, help="Output MP4 file path")
    parser.add_argument("--upload-supabase", action="store_true", default=False, help="Upload to Supabase Storage (default: False to conserve bucket quota)")
    parser.add_argument("--no-supabase", action="store_true", default=True, help="Skip uploading to Supabase Storage")
    parser.add_argument("--voice", type=str, default="en-IN-NeerjaNeural", help="Offline fallback voice")
    parser.add_argument("--audio-engine", type=str, default="model", choices=["auto", "sarvam", "offline", "model"], help="Audio synthesis engine")
    parser.add_argument("--scratch", action="store_true", default=True, help="Purge stale cached images to generate from scratch")
    args = parser.parse_args()

    # Supabase storage disabled by default to prevent exhausting free bucket limits
    upload_supabase_flag = args.upload_supabase and not args.no_supabase

    run_pipeline(
        count=args.count,
        mode=args.mode,
        sarvam_api_key=args.sarvam_key or os.getenv("SARVAM_API_KEY"),
        drive_folder=args.drive_folder or os.getenv("GDRIVE_FOLDER_ID"),
        output_path=args.output,
        upload_supabase=upload_supabase_flag,
        offline_voice=args.voice,
        audio_engine=args.audio_engine,
        from_scratch=args.scratch,
    )


if __name__ == "__main__":
    main()
