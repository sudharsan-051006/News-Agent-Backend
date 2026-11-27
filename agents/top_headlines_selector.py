"""Top Headlines Selector Agent for News-Agent-Backend.

Fetches and curates the top headlines (default 25) across all categories
and channels from Supabase news_cache, verifying image accessibility and
preparing structured metadata for broadcast video generation.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Add project root to sys.path so imports work standalone and as a module
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import cv2
import requests
import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Optional
from supabase_client import supabase
from agents.image_quality_filter import fetch_and_validate_image
from agents.news_video_generator import resolve_actual_publisher

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# Domains known to block direct external scraping with 403
BLOCKED_DOMAINS = {"c.ndtvimg.com"}


def _is_image_accessible(url: str, timeout: float = 4.0) -> bool:
    """Check if an image URL is accessible and returns valid image content."""
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False

    domain = url.split("/")[2] if "://" in url else ""
    if domain in BLOCKED_DOMAINS:
        return False

    try:
        # Quick HEAD or GET request to verify HTTP 200 and image mime type
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, stream=True)
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "")
            # Verify it is an image or binary
            if "image" in content_type or int(resp.headers.get("Content-Length", 1000)) > 500:
                return True
    except Exception:
        pass
    return False


def _clean_headline(text: str) -> str:
    """Clean and standardize headline text for broadcast display."""
    if not text:
        return "Breaking News Update"
    text = re.sub(r'[\r\n\t]+', ' ', text).strip()
    text = re.sub(r'^["\']|["\']$', '', text).strip()
    # Remove source suffix if present (e.g. " - BBC News")
    text = re.sub(r'\s*[-|]\s*[A-Z][A-Za-z0-9\s]{2,15}$', '', text).strip()
    if len(text) > 95:
        text = text[:92].rsplit(' ', 1)[0] + '...'
    return text


BROADCAST_CONNECTORS = [
    "Starting with our top story: ",
    "In another major development: ",
    "Moving forward: ",
    "Turning to our next report: ",
    "In other key news: ",
    "Next up: ",
    "Meanwhile: ",
    "Switching focus: ",
    "In a significant update: ",
    "Also making headlines: ",
    "Shifting our attention: ",
    "In our next story: ",
    "Breaking update: ",
    "Across the nation: ",
    "On the global front: ",
    "In business and markets: ",
    "From the tech world: ",
    "From the world of sports: ",
    "In entertainment: ",
    "Continuing our coverage: ",
    "In another headline: ",
    "Further reports indicate: ",
    "Also developing right now: ",
    "As we follow key developments: ",
    "And in our final headline: ",
]


def _create_narration_script(article: Dict[str, Any], index: int = 1) -> str:
    """Create a natural spoken narration script with varied broadcast connectors (no repetitive category prefixes)."""
    summary = article.get("ai_summary") or ""
    headline = _clean_headline(article.get("ai_headline") or article.get("original_title") or "")

    connector = BROADCAST_CONNECTORS[(index - 1) % len(BROADCAST_CONNECTORS)]

    if summary and len(summary) > 25:
        first_sentence = summary.split(". ")[0].strip()
        if not first_sentence.endswith("."):
            first_sentence += "."
        script = f"{connector}{headline}. {first_sentence}"
    else:
        script = f"{connector}{headline}."

    # Clean markdown, stray URLs, and multiple spaces
    script = re.sub(r'https?://\S+', '', script)
    script = re.sub(r'[*_#]', '', script)
    script = re.sub(r'\s+', ' ', script).strip()
    return script


def get_top_headlines(
    target_count: int = 25,
    verify_images: bool = True,
    categories: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Retrieve and balance top headlines from Supabase across available categories.

    Args:
        target_count: Total number of headlines to return (default: 25).
        verify_images: Whether to verify image accessibility via HTTP check.
        categories: Optional list of categories to filter by.

    Returns:
        List of curated headline dicts with index, headline, narration, image_url, etc.
    """
    print(f"📡 Querying Supabase news_cache for top {target_count} headlines...")

    query = supabase.table("news_cache").select(
        "id, category, original_title, ai_headline, ai_summary, image_url, source, link, published_at"
    ).not_.is_("image_url", "null")

    if categories:
        query = query.in_("category", categories)

    res = query.order("published_at", desc=True).limit(200).execute()
    raw_articles = res.data or []

    if not raw_articles:
        print("⚠️ No articles found in news_cache with image_url.")
        return []

    print(f"📦 Retrieved {len(raw_articles)} candidate articles from Supabase.")

    # Group articles by category
    by_category = defaultdict(list)
    for a in raw_articles:
        cat = (a.get("category") or "general").lower()
        by_category[cat].append(a)

    cat_list = sorted(by_category.keys())
    print(f"📂 Available categories ({len(cat_list)}): {cat_list}")

    # Calculate quota per category to achieve target_count
    per_cat_quota = max(1, target_count // len(cat_list)) if cat_list else target_count

    curated = []
    seen_titles = set()

    # Round-robin selection across categories
    for cat in cat_list:
        cat_articles = by_category[cat]
        added_for_cat = 0

        for art in cat_articles:
            if added_for_cat >= per_cat_quota:
                break

            title = _clean_headline(art.get("ai_headline") or art.get("original_title") or "")
            title_key = title.lower()[:40]
            if title_key in seen_titles:
                continue

            img_url = art.get("image_url")
            img_arr = None
            if verify_images:
                valid_photo, img_arr, reason = fetch_and_validate_image(img_url, min_width=350, min_height=200)
                if not valid_photo or img_arr is None:
                    # Skip channel logos, icons, placeholders, or tiny thumbnails
                    continue

            seen_titles.add(title_key)
            narration = _create_narration_script(art)

            # Save the exact downloaded and verified image to disk
            images_dir = ROOT_DIR / "outputs" / "verified_images"
            images_dir.mkdir(parents=True, exist_ok=True)
            url_hash = hashlib.md5((img_url or "").encode()).hexdigest()[:8]
            saved_img_path = str(images_dir / f"art_{len(curated)+1:02d}_{url_hash}.jpg")
            if img_arr is not None:
                cv2.imwrite(saved_img_path, img_arr)

            curated.append({
                "index": len(curated) + 1,
                "category": (art.get("category") or "General").upper(),
                "headline": title,
                "original_title": art.get("original_title"),
                "ai_summary": art.get("ai_summary") or "",
                "narration_script": narration,
                "image_url": img_url,
                "image_path": saved_img_path if img_arr is not None else None,
                "source": resolve_actual_publisher(art.get("source"), art.get("link")) or "",
                "published_at": art.get("published_at"),
                "link": art.get("link"),
            })
            added_for_cat += 1

    # If still below target_count, fill remaining slots with any verified articles
    if len(curated) < target_count:
        for cat in cat_list:
            for art in by_category[cat]:
                if len(curated) >= target_count:
                    break

                title = _clean_headline(art.get("ai_headline") or art.get("original_title") or "")
                title_key = title.lower()[:40]
                if title_key in seen_titles:
                    continue

                img_url = art.get("image_url")
                img_arr = None
                if verify_images:
                    valid_photo, img_arr, reason = fetch_and_validate_image(img_url, min_width=350, min_height=200)
                    if not valid_photo or img_arr is None:
                        continue

                seen_titles.add(title_key)
                images_dir = ROOT_DIR / "outputs" / "verified_images"
                images_dir.mkdir(parents=True, exist_ok=True)
                url_hash = hashlib.md5((img_url or "").encode()).hexdigest()[:8]
                saved_img_path = str(images_dir / f"art_{len(curated)+1:02d}_{url_hash}.jpg")
                if img_arr is not None:
                    cv2.imwrite(saved_img_path, img_arr)

                curated.append({
                    "index": len(curated) + 1,
                    "category": (art.get("category") or "General").upper(),
                    "headline": title,
                    "original_title": art.get("original_title"),
                    "ai_summary": art.get("ai_summary") or "",
                    "narration_script": _create_narration_script(art),
                    "image_url": img_url,
                    "image_path": saved_img_path if img_arr is not None else None,
                    "source": resolve_actual_publisher(art.get("source"), art.get("link")) or "",
                    "published_at": art.get("published_at"),
                    "link": art.get("link"),
                })

    # Renumber indices 1..len(curated) and apply varied broadcast connectors
    curated = curated[:target_count]
    for idx, item in enumerate(curated, start=1):
        item["index"] = idx
        item["narration_script"] = _create_narration_script(item, index=idx)

    print(f"✅ Successfully curated {len(curated)} top headlines across {len(cat_list)} categories.")
    return curated


if __name__ == "__main__":
    headlines = get_top_headlines(target_count=25, verify_images=True)
    print(f"\n--- Previewing Top {len(headlines)} Headlines ---")
    for h in headlines[:5]:
        print(f"[{h['index']:02d}] {h['category']}: {h['headline']}")
        print(f"     Narration: {h['narration_script']}")
        print(f"     Image: {h['image_url'][:70]}...")
