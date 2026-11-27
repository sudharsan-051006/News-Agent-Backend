"""Automated Master Broadcast Workflow Runner.

Orchestrates the entire video generation, distribution, and local deployment lifecycle:
1. Generates Top 25 Daily News Bulletin (Local LLM + Neural Audio + Ken Burns)
2. Generates Top Trending Stories Bulletin (Neon DB + Local LLM + Neural Audio)
3. Deploys fresh MP4 videos to local web player: news_web/public/broadcast/
4. Uploads to Supabase CDN for high-speed streaming
5. Triggers Google Apps Script Webhook to transfer videos into Google Drive

Usage:
    python run_broadcast_workflow.py
    python run_broadcast_workflow.py --mode top25
    python run_broadcast_workflow.py --mode trending
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv()

from generate_headlines_video_pipeline import run_pipeline


def deploy_to_news_web(video_path: str, destination_name: str) -> bool:
    """Copy rendered MP4 to news_web public static folder for zero-API local playback."""
    try:
        web_public = ROOT_DIR.parent / "news_web" / "public" / "broadcast"
        web_public.mkdir(parents=True, exist_ok=True)
        target = web_public / destination_name
        shutil.copy2(video_path, target)
        print(f"📦 [Web Deployment] Copied video to local player: {target} ({os.path.getsize(target)/(1024*1024):.2f} MB)")
        return True
    except Exception as exc:
        print(f"⚠️ [Web Deployment] Could not copy to news_web/public/broadcast: {exc}")
        return False


def run_broadcast_workflow(
    mode: str = "both",
    top25_count: int = 25,
    trending_count: int = 10,
    audio_engine: str = "model",
    from_scratch: bool = True,
) -> dict:
    start_time = time.time()
    results = {}

    print("\n" + "=" * 70)
    print("      ELINITY MASTER AI BROADCAST VIDEO WORKFLOW")
    print("=" * 70)
    print(f"Workflow Mode:         {mode.upper()}")
    print(f"Audio Engine:          {audio_engine} (Sarvam bypassed: {audio_engine != 'sarvam'})")
    print(f"Scratch Generation:    {from_scratch}")
    print(f"Drive Webhook Target:  {os.getenv('GDRIVE_APPS_SCRIPT_URL', 'Configured')}")
    print("=" * 70 + "\n")

    # 1. Top 25 Daily News Bulletin
    if mode.lower() in ("both", "top25"):
        print("\n🚀 >>> [WORKFLOW PHASE 1] Generating Top 25 Daily News Bulletin <<<\n")
        t0 = time.time()
        res_top25 = run_pipeline(
            count=top25_count,
            mode="top25",
            audio_engine=audio_engine,
            from_scratch=from_scratch,
            upload_supabase=True,
        )
        results["top25"] = res_top25
        if res_top25.get("status") == "success" and res_top25.get("video_path"):
            deploy_to_news_web(res_top25["video_path"], "top25_headlines_latest.mp4")
        print(f"✅ Phase 1 complete in {time.time() - t0:.1f}s.")

    # 2. Trending Stories Bulletin
    if mode.lower() in ("both", "trending"):
        print("\n🚀 >>> [WORKFLOW PHASE 2] Generating Trending Stories Bulletin <<<\n")
        t0 = time.time()
        res_trend = run_pipeline(
            count=trending_count,
            mode="trending",
            audio_engine=audio_engine,
            from_scratch=from_scratch,
            upload_supabase=True,
        )
        results["trending"] = res_trend
        if res_trend.get("status") == "success" and res_trend.get("video_path"):
            deploy_to_news_web(res_trend["video_path"], "trending_headlines_latest.mp4")
        print(f"✅ Phase 2 complete in {time.time() - t0:.1f}s.")

    total_duration = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"🎉 MASTER BROADCAST WORKFLOW FINISHED ({total_duration:.1f}s / {total_duration/60:.1f} min)")
    print("=" * 70)
    for m, r in results.items():
        if r.get("status") == "success":
            print(f"  • {m.upper()}: {r.get('video_path')} | CDN: {r.get('supabase_cdn_url')}")
    print("=" * 70 + "\n")

    return results


def main():
    parser = argparse.ArgumentParser(description="Run Elinity Master AI Broadcast Video Workflow")
    parser.add_argument("--mode", type=str, default="both", choices=["both", "top25", "trending"], help="Workflow mode")
    parser.add_argument("--top25-count", type=int, default=25, help="Headlines count for Top 25")
    parser.add_argument("--trending-count", type=int, default=10, help="Stories count for Trending")
    parser.add_argument("--audio-engine", type=str, default="model", choices=["model", "sarvam"], help="Speech engine")
    parser.add_argument("--no-scratch", action="store_true", help="Do not purge image cache")
    args = parser.parse_args()

    run_broadcast_workflow(
        mode=args.mode,
        top25_count=args.top25_count,
        trending_count=args.trending_count,
        audio_engine=args.audio_engine,
        from_scratch=not args.no_scratch,
    )


if __name__ == "__main__":
    main()
