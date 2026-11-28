"""Master Autonomous Incident Spotlight Pipeline for Elinity News Network.

Discovers active trending incidents from Neon DB (V(t) >= 1.5x),
fact-checks multi-source evidence across primary sources and DuckDuckGo,
synthesizes an authoritative long-form article into the database for the frontend reader,
and produces a 60-second broadcast spotlight video uploaded to Google Drive.
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from agents.investigative_fact_checker import (
    fetch_unprocessed_trending_incidents,
    investigate_incident,
)
from agents.incident_article_writer import (
    write_incident_article,
    persist_incident_article_to_db,
)
from agents.short_incident_video_generator import generate_short_incident_video


def run_spotlight_pipeline(
    min_velocity: float = 1.5,
    max_incidents: int = 3,
    drive_folder: Optional[str] = None,
    output_dir: Optional[str] = None,
    force_all: bool = False,
) -> Dict[str, Any]:
    """Execute the multi-incident spotlight pipeline."""
    start_time = time.time()
    out_dir = Path(output_dir) if output_dir else (ROOT_DIR / "outputs" / "shorts")
    out_dir.mkdir(parents=True, exist_ok=True)
    target_drive = drive_folder or os.getenv("GDRIVE_FOLDER_ID")

    print("\n" + "=" * 70)
    print("      ELINITY NEWS NETWORK: AUTONOMOUS INCIDENT SPOTLIGHT PIPELINE")
    print("=" * 70)
    print(f"Velocity Threshold:    V(t) >= {min_velocity}x")
    print(f"Max Incidents Per Run: {max_incidents}")
    print(f"Google Drive Target:   {target_drive or 'Configured via GAS'}")
    print(f"Outputs Directory:     {out_dir}")
    print("=" * 70 + "\n")

    # Step 1: Discover candidate incidents
    incidents = fetch_unprocessed_trending_incidents(
        min_velocity=min_velocity,
        limit=max_incidents,
        force_all=force_all,
    )
    if not incidents:
        print("ℹ️ No new trending incidents meet the velocity threshold right now.")
        return {"status": "idle", "processed_count": 0, "incidents": []}

    print(f"\n⚡ Discovered {len(incidents)} active incident(s) for dedicated coverage:")
    for idx, inc in enumerate(incidents, start=1):
        print(f"   [{idx}] {inc['topic_name']} ({inc['pillar']} • {inc['velocity_score']}x)")

    results: List[Dict[str, Any]] = []

    # Step 2: Process each incident sequentially
    for idx, inc in enumerate(incidents, start=1):
        print("\n" + "#" * 70)
        print(f"PRODUCING SPOTLIGHT [{idx}/{len(incidents)}]: '{inc['topic_name']}'")
        print("#" * 70)
        incident_t0 = time.time()

        try:
            # 1. Fact-Checking & Evidence Ingestion
            dossier = investigate_incident(inc)

            # 2. Write & Persist In-Depth Journalistic Article
            article = write_incident_article(dossier)
            persist_incident_article_to_db(article)

            # 3. Generate 60-Second Video Spotlight & Upload
            video_result = generate_short_incident_video(
                article_dossier=article,
                output_dir=out_dir,
                drive_folder=target_drive,
            )

            incident_elapsed = time.time() - incident_t0
            results.append({
                "incident_id": inc["id"],
                "topic_name": inc["topic_name"],
                "headline": article["headline"],
                "duration": video_result.get("duration", 60.0),
                "video_file": video_result.get("video_filename"),
                "drive_url": video_result.get("drive_url"),
                "status": "success",
                "elapsed_seconds": round(incident_elapsed, 1),
            })

            print(f"✅ Finished Incident [{idx}/{len(incidents)}] in {incident_elapsed:.1f}s")

        except Exception as err:
            print(f"❌ Error processing incident '{inc['topic_name']}': {err}")
            results.append({
                "incident_id": inc["id"],
                "topic_name": inc["topic_name"],
                "status": "failed",
                "error": str(err),
            })

    total_time = time.time() - start_time
    print("\n" + "=" * 70)
    print("🎉 ALL SPOTLIGHT INCIDENTS PROCESSED SUCCESSFULLY")
    print("=" * 70)
    print(f"Total Incidents Processed: {len(results)}")
    print(f"Total Pipeline Runtime:    {total_time:.1f}s ({total_time/60:.1f} min)")
    for r in results:
        status_icon = "✓" if r["status"] == "success" else "✗"
        print(f"  {status_icon} [{r.get('headline') or r['topic_name']}] -> {r.get('video_file', 'No video')} ({r.get('elapsed_seconds', 0)}s)")
    print("=" * 70 + "\n")

    return {
        "status": "success",
        "processed_count": len(results),
        "total_runtime_seconds": round(total_time, 1),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Autonomous Incident Spotlight & 60s Video Pipeline")
    parser.add_argument("--min-velocity", type=float, default=1.5, help="Minimum velocity surge threshold (default: 1.5)")
    parser.add_argument("--limit", type=int, default=3, help="Maximum incidents to process per run (default: 3)")
    parser.add_argument("--force", action="store_true", help="Force re-processing of incidents even if already covered")
    parser.add_argument("--drive-folder", type=str, default=None, help="Google Drive folder ID or share link")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for generated shorts")
    args = parser.parse_args()

    run_spotlight_pipeline(
        min_velocity=args.min_velocity,
        max_incidents=args.limit,
        drive_folder=args.drive_folder,
        output_dir=args.output_dir,
        force_all=args.force,
    )


if __name__ == "__main__":
    main()
