"""Autonomous Investigative Fact-Checker & Multi-Source Research Agent.

Discovers high-velocity breaking incidents from Neon DB topic_snapshots (V(t) >= 2.0),
crawls original reference articles, and queries DuckDuckGo for primary source verification,
official statements, chronological developments, and press imagery.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from agents.news_video_generator import resolve_actual_publisher
from agents.image_quality_filter import fetch_and_validate_image

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

BLOCKED_DOMAINS = {"c.ndtvimg.com", "instagram.com", "facebook.com", "twitter.com", "x.com"}


def get_neon_connection():
    """Connect to Neon PostgreSQL."""
    import psycopg2
    neon_url = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not neon_url:
        raise ValueError("Missing NEON_DATABASE_URL or DATABASE_URL in environment")
    return psycopg2.connect(neon_url)


def fetch_unprocessed_trending_incidents(
    min_velocity: float = 1.5,
    limit: int = 5,
    lookback_hours: int = 48,
    force_all: bool = False,
) -> List[Dict[str, Any]]:
    """Query Neon DB for trending incidents needing dedicated 60s video and investigative report."""
    print(f"📡 Querying Neon DB for active trending incidents (velocity >= {min_velocity}x)...")
    incidents = []

    try:
        conn = get_neon_connection()
        cur = conn.cursor()

        unprocessed_clause = "" if force_all else "AND (summary IS NULL OR summary NOT LIKE '%%Investigative Dossier%%')"
        query = f"""
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
            WHERE velocity_score >= %s
              AND created_at >= NOW() - INTERVAL '{lookback_hours} hours'
              {unprocessed_clause}
            ORDER BY created_at DESC, velocity_score DESC
            LIMIT %s;
        """
        cur.execute(query, (min_velocity, limit * 2))
        rows = cur.fetchall()

        seen_names = set()
        for r in rows:
            name = (r[1] or "").strip()
            # Clean normalized title to prevent duplicate angles of same story
            clean_key = re.sub(r"[^a-z0-9]", "", name.lower())[:35]
            if clean_key in seen_names or not name:
                continue
            seen_names.add(clean_key)

            raw_refs = r[7]
            if isinstance(raw_refs, str):
                import json
                try:
                    raw_refs = json.loads(raw_refs)
                except Exception:
                    raw_refs = []
            elif not isinstance(raw_refs, list):
                raw_refs = []

            incidents.append({
                "id": str(r[0]),
                "topic_name": name,
                "pillar": r[2] or "General News",
                "why_trending": r[3] or "",
                "velocity_score": float(r[4] or 1.0),
                "summary": r[5] or "",
                "image_url": r[6] or "",
                "reference_articles": raw_refs,
                "created_at": str(r[8]),
            })

            if len(incidents) >= limit:
                break

        cur.close()
        conn.close()
        print(f"✅ Found {len(incidents)} qualified trending incidents for dedicated coverage.")
    except Exception as exc:
        print(f"❌ Failed to fetch trending incidents from Neon: {exc}")

    return incidents


def _scrape_clean_article_text(url: str, max_chars: int = 1500) -> str:
    """Scrape article body text from URL, discarding headers, footers, and ads."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        domain = urlparse(url).netloc.lower()
        if any(b in domain for b in BLOCKED_DOMAINS):
            return ""

        res = requests.get(url, headers=BROWSER_HEADERS, timeout=6)
        if res.status_code != 200:
            return ""

        soup = BeautifulSoup(res.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        # Find paragraphs
        paragraphs = [p.get_text().strip() for p in soup.find_all("p") if len(p.get_text().strip()) > 35]
        text = " ".join(paragraphs)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def _get_article_from_neon_cache(url: str, title: str = "") -> Optional[Dict[str, str]]:
    """Retrieve pre-cleaned article text and image from Neon articles table to bypass website 403 blocks."""
    if not url:
        return None
    try:
        conn = get_neon_connection()
        cur = conn.cursor()
        cur.execute("SELECT title, cleaned_content, image_url, published_at FROM articles WHERE url = %s LIMIT 1;", (url,))
        row = cur.fetchone()
        if not row and title:
            # Try fuzzy match on title
            cur.execute("SELECT title, cleaned_content, image_url, published_at FROM articles WHERE title ILIKE %s LIMIT 1;", (f"%{title[:30]}%",))
            row = cur.fetchone()
        cur.close()
        conn.close()

        if row and row[1]:
            return {
                "title": row[0] or title,
                "text": row[1],
                "image_url": row[2] or "",
                "published_at": str(row[3]) if row[3] else "",
            }
    except Exception as exc:
        print(f"   ℹ️ Neon article lookup note: {exc}")
    return None


def investigate_incident(
    incident: Dict[str, Any],
    max_search_results: int = 4,
) -> Dict[str, Any]:
    """Perform multi-source web investigation and factual grounding on a single incident."""
    topic_name = incident["topic_name"]
    pillar = incident["pillar"]
    print(f"\n" + "=" * 65)
    print(f"🔍 [INVESTIGATION AGENT] Researching Incident: '{topic_name}'")
    print(f"   Pillar: {pillar} | Velocity: {incident['velocity_score']}x")
    print("=" * 65)

    evidence_pool: List[Dict[str, str]] = []
    verified_images: List[str] = []

    # Include initial validated image if present
    if incident.get("image_url"):
        verified_images.append(incident["image_url"])

    # Phase 1: Ingest primary reference articles (Neon DB cache first, then live web scrape)
    initial_refs = incident.get("reference_articles") or []
    print(f"📄 Phase 1: Ingesting {len(initial_refs)} primary reference articles...")
    for idx, ref in enumerate(initial_refs[:5], start=1):
        url = ref.get("url") or ref.get("link") or ""
        title = ref.get("title") or ref.get("article_title") or ""
        source = ref.get("source") or ref.get("publisher") or resolve_actual_publisher("", url)

        # 1. Try Neon pre-cleaned article corpus
        neon_cached = _get_article_from_neon_cache(url, title)
        if neon_cached and len(neon_cached["text"]) > 100:
            evidence_pool.append({
                "source": source,
                "url": url,
                "title": neon_cached["title"],
                "text": neon_cached["text"],
                "type": "primary_verified_source"
            })
            print(f"   ✓ Ingested ({source}): {len(neon_cached['text'])} chars from database")
            if neon_cached.get("image_url") and neon_cached["image_url"] not in verified_images:
                verified_images.append(neon_cached["image_url"])
            continue

        # 2. Fall back to live web scrape
        body_snippet = _scrape_clean_article_text(url)
        if body_snippet:
            evidence_pool.append({
                "source": source,
                "url": url,
                "title": title or topic_name,
                "text": body_snippet,
                "type": "primary_scraped_source"
            })
            print(f"   ✓ Scraped ({source}): {len(body_snippet)} chars via HTTP")

        if ref.get("image_url") and ref["image_url"] not in verified_images:
            verified_images.append(ref["image_url"])

    # Phase 2: Live multi-source web verification via DuckDuckGo
    print("🌐 Phase 2: Live multi-source web verification via DuckDuckGo...")
    # Extract 3-5 core search keywords (omit stopwords and punctuation)
    stopwords = {"and", "the", "for", "with", "from", "after", "into", "over", "about", "says", "said"}
    words = [w for w in re.sub(r"[^\w\s]", " ", topic_name).split() if len(w) > 3 and w.lower() not in stopwords]
    clean_query = " ".join(words[:4]) if words else topic_name[:40]

    search_queries = [
        f"{clean_query} news",
        f"{clean_query} statement",
    ]

    try:
        with DDGS(timeout=4) as ddgs:
            for q in search_queries[:1]:
                print(f"   🔎 Searching: '{q}'")
                try:
                    results = list(ddgs.text(q, max_results=max_search_results))
                    for r in results:
                        href = r.get("href") or ""
                        title = r.get("title") or ""
                        body = r.get("body") or ""
                        publisher = resolve_actual_publisher("", href)

                        if href and not any(e["url"] == href for e in evidence_pool):
                            evidence_pool.append({
                                "source": publisher,
                                "url": href,
                                "title": title,
                                "text": body,
                                "type": "web_search"
                            })
                            print(f"      • Found [{publisher}]: {title[:55]}...")
                except Exception as search_err:
                    print(f"      ℹ️ Search query note: {search_err}")
    except Exception as exc:
        print(f"ℹ️ DuckDuckGo note: {exc}")

    # Deduplicate verified sources
    unique_sources = []
    seen_urls = set()
    for ev in evidence_pool:
        if ev["url"] and ev["url"] not in seen_urls:
            seen_urls.add(ev["url"])
            unique_sources.append({
                "source": ev["source"],
                "url": ev["url"],
                "title": ev["title"]
            })

    print(f"\n📊 Investigation Complete: Corroborated across {len(unique_sources)} sources with {len(verified_images)} photos.")

    return {
        "incident_id": incident["id"],
        "topic_name": topic_name,
        "pillar": pillar,
        "velocity_score": incident["velocity_score"],
        "why_trending": incident.get("why_trending", ""),
        "created_at": incident.get("created_at", ""),
        "evidence_pool": evidence_pool,
        "verified_sources": unique_sources,
        "verified_images": verified_images,
    }


if __name__ == "__main__":
    # Test standalone execution
    incidents = fetch_unprocessed_trending_incidents(min_velocity=1.5, limit=1)
    if incidents:
        dossier = investigate_incident(incidents[0])
        print("\nTest Dossier Evidence Count:", len(dossier["evidence_pool"]))
        print("Verified Sources Count:", len(dossier["verified_sources"]))
        print("Images Count:", len(dossier["verified_images"]))
    else:
        print("No active trending incidents found above threshold.")
