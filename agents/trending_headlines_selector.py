"""Trending Headlines Selector Agent for News-Agent-Backend.

Fetches and curates top trending stories from Neon topic_snapshots (and Supabase),
validating real photography and preparing structured metadata for trending broadcast video.
"""
from __future__ import annotations

import os
import sys
import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv()

from agents.image_quality_filter import fetch_and_validate_image
from agents.top_headlines_selector import _clean_headline
from agents.news_video_generator import resolve_actual_publisher

NEON_DATABASE_URL = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")


def get_trending_headlines(
    target_count: int = 15,
    verify_images: bool = True,
) -> List[Dict[str, Any]]:
    """Retrieve and curate top trending topics from Neon topic_snapshots.

    Returns:
        List of curated trending story dictionaries with 1-to-1 matching image files.
    """
    print(f"📡 Querying Neon database for top trending topics (target: {target_count})...")
    raw_topics = []

    if not NEON_DATABASE_URL:
        print("⚠️ Neon database URL is not configured (NEON_DATABASE_URL or DATABASE_URL).")
        return []

    try:
        import psycopg2
        conn = psycopg2.connect(NEON_DATABASE_URL)
        cur = conn.cursor()
        query = """
            SELECT 
                id, 
                topic_name, 
                pillar, 
                why_trending, 
                velocity_score, 
                summary, 
                image_url, 
                reference_articles, 
                created_at
            FROM topic_snapshots
            WHERE image_url IS NOT NULL
            ORDER BY created_at DESC, velocity_score DESC
            LIMIT 50;
        """
        cur.execute(query)
        rows = cur.fetchall()
        for r in rows:
            raw_topics.append({
                "id": str(r[0]),
                "topic_name": r[1],
                "pillar": r[2] or "General",
                "why_trending": r[3] or "",
                "velocity_score": float(r[4] or 0),
                "summary": r[5] or "",
                "image_url": r[6],
                "reference_articles": r[7],
                "created_at": str(r[8]),
            })
        cur.close()
        conn.close()
        print(f"📦 Retrieved {len(raw_topics)} candidate trending topics from Neon.")
    except Exception as exc:
        print(f"⚠️ Neon connection error: {exc}")

    curated = []
    seen_titles = set()
    images_dir = ROOT_DIR / "outputs" / "verified_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    for item in raw_topics:
        if len(curated) >= target_count:
            break

        title = _clean_headline(item["topic_name"])
        title_key = title.lower()[:40]
        if title_key in seen_titles:
            continue

        img_url = item.get("image_url")
        img_arr = None

        if verify_images and img_url:
            valid_photo, img_arr, reason = fetch_and_validate_image(
                img_url, min_width=320, min_height=180
            )
            if not valid_photo or img_arr is None:
                continue

        seen_titles.add(title_key)

        # Extract primary reference link and source name
        refs = item.get("reference_articles") or []
        if isinstance(refs, str):
            try:
                refs = json.loads(refs)
            except Exception:
                refs = []

        primary_link = ""
        primary_source = "News Network"
        if refs and isinstance(refs, list):
            primary_link = refs[0].get("url") or refs[0].get("link") or ""
            primary_source = refs[0].get("source") or refs[0].get("title", "")[:20]

        # Save verified photo to disk to guarantee 100% 1-to-1 match
        url_hash = hashlib.md5((img_url or "").encode()).hexdigest()[:8]
        saved_img_path = str(images_dir / f"trend_{len(curated)+1:02d}_{url_hash}.jpg")
        if img_arr is not None:
            cv2.imwrite(saved_img_path, img_arr)

        curated.append({
            "index": len(curated) + 1,
            "category": item["pillar"].upper(),
            "headline": title,
            "original_title": item["topic_name"],
            "ai_summary": item["why_trending"] or item["summary"],
            "why_trending": item["why_trending"],
            "image_url": img_url,
            "image_path": saved_img_path if img_arr is not None else None,
            "source": resolve_actual_publisher(primary_source, primary_link) or "",
            "link": primary_link,
            "velocity_score": item["velocity_score"],
            "is_trending": True,
        })

    print(f"✅ Curated {len(curated)} verified trending topics.")
    return curated


if __name__ == "__main__":
    topics = get_trending_headlines(target_count=10)
    for t in topics:
        print(f"[{t['index']:02d}] {t['category']}: {t['headline']}")
        print(f"     Why: {t['why_trending']}")
        print(f"     Image: {t['image_path']}")
        print(f"     Link: {t['link']}")
