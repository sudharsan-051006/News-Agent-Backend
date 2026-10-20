"""Fetch RSS article metadata for the separate Elinity trending pipeline.

This collector intentionally avoids the main collector's article-image lookups
and per-category top-five cap, because trend detection needs coverage history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests

from agents.trend_detector import publisher_from_feed

TIMEOUT_SECONDS = 12
USER_AGENT = "ElinityTrending/1.0 (+RSS trend monitoring)"
MAX_ENTRIES_PER_FEED = 40


def _published(entry: dict) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        from calendar import timegm
        return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def fetch_trend_articles(sources: list[dict]) -> list[dict]:
    articles: list[dict] = []
    seen_urls: set[str] = set()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for source in sources:
        feed_url = (source.get("rss_url") or "").strip()
        category = (source.get("category") or "General").strip()
        if not feed_url:
            continue
        try:
            response = session.get(feed_url, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except (requests.RequestException, ValueError) as exc:
            print(f"⚠️ Trending RSS fetch failed for {feed_url}: {type(exc).__name__}")
            continue

        publisher = publisher_from_feed(feed_url)
        for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
            title = str(entry.get("title") or "").strip()
            link = str(entry.get("link") or "").strip()
            if not title or not link or link in seen_urls:
                continue
            parsed_link = urlparse(link)
            if parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
                continue
            seen_urls.add(link)
            articles.append({
                "title": title,
                "link": link,
                "category": category,
                "feed_url": feed_url,
                "publisher": publisher,
                "published_at": _published(entry),
                "summary": str(entry.get("summary") or "")[:2000],
            })

    print(f"📰 Trending collector fetched {len(articles)} unique RSS articles from {len(sources)} feeds.")
    return articles
