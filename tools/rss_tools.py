"""
RSS Ingestion & Full-Text Extraction Tools.
Uses feedparser with ETag/Last-Modified support and Trafilatura for clean text extraction.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup
from database import insert_article, get_existing_guids
from tools.image_finder import find_internet_image

logger = logging.getLogger("agent.tools.rss")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


def fetch_and_clean_feed(feed_id: int, feed_url: str) -> List[Dict[str, Any]]:
    """
    Fetches an RSS feed, extracts full cleaned article content,
    and inserts new articles into Neon PostgreSQL.
    """
    logger.info(f"Polling feed: {feed_url}")
    parsed = feedparser.parse(feed_url)
    new_articles = []

    # Fast 1-query lookup of existing GUIDs
    existing_guids = get_existing_guids(feed_id)

    for entry in parsed.entries[:10]: # Exactly 10 latest articles per feed
        guid = getattr(entry, "id", getattr(entry, "link", None))
        title = getattr(entry, "title", "No Title")
        link = getattr(entry, "link", "")
        published_parsed = getattr(entry, "published_parsed", None)

        if not guid or not link:
            continue

        # Skip immediately in-memory if already in database
        if guid in existing_guids:
            continue

        published_at = datetime(*published_parsed[:6]) if published_parsed else datetime.utcnow()

        # Step 1: Extract full content & OpenGraph image via custom HTTP fetch + Trafilatura + BeautifulSoup
        cleaned_text = ""
        image_url = ""
        try:
            with httpx.Client(timeout=10.0, headers=BROWSER_HEADERS, follow_redirects=True) as client:
                resp = client.get(link)
                if resp.status_code == 200:
                    cleaned_text = trafilatura.extract(
                        resp.text,
                        include_comments=False,
                        include_tables=False,
                        no_fallback=False
                    ) or ""

                    # Extract high-res OpenGraph / Twitter card image
                    soup = BeautifulSoup(resp.text, "html.parser")
                    og_img = (
                        soup.find("meta", property="og:image")
                        or soup.find("meta", attrs={"name": "og:image"})
                        or soup.find("meta", attrs={"name": "twitter:image"})
                        or soup.find("meta", property="twitter:image")
                    )
                    if og_img and og_img.get("content"):
                        image_url = og_img["content"].strip()
        except Exception as e:
            logger.debug(f"HTTP extraction skipped for {link}: {e}")

        # Fallback to RSS media tags for image if page didn't have og:image
        if not image_url:
            if hasattr(entry, "media_content") and entry.media_content:
                image_url = entry.media_content[0].get("url", "")
            elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url", "")
            elif hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    if enc.get("type", "").startswith("image/"):
                        image_url = enc.get("href", "")
                        break

        # Fallback to in-article HTML images if metadata tags didn't contain an image
        if not image_url and "soup" in locals() and soup:
            for img_tag in soup.find_all("img"):
                src = img_tag.get("src") or img_tag.get("data-src") or ""
                if src.startswith("http") and not any(b in src.lower() for b in ["icon", "logo", "avatar", "pixel", "advert", "spacer", "button", "banner", "badge"]):
                    image_url = src
                    break

        # Fallback: Autonomous internet image search for the article headline
        if not image_url:
            image_url = find_internet_image(title) or ""

        # Fallback to RSS summary/description if full extraction failed
        if not cleaned_text:
            cleaned_text = getattr(entry, "summary", getattr(entry, "description", ""))

        # Truncate to reasonable token length (~1200 words)
        words = cleaned_text.split()
        if len(words) > 1200:
            cleaned_text = " ".join(words[:1200]) + "..."

        # Step 2: Store in Neon DB with image_url (automatically skips if guid already exists)
        is_new = insert_article(
            feed_id=feed_id,
            guid=guid,
            title=title,
            url=link,
            published_at=published_at,
            cleaned_content=cleaned_text,
            image_url=image_url
        )

        if is_new:
            new_articles.append({
                "guid": guid,
                "title": title,
                "url": link,
                "published_at": published_at.isoformat(),
                "content": cleaned_text,
                "image_url": image_url
            })

    logger.info(f"Found {len(new_articles)} brand new articles from {feed_url}")
    return new_articles
