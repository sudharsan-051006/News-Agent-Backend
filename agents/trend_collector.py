"""Fetch RSS article metadata, including available article thumbnail URLs.

This collector intentionally avoids the main collector's per-category top-five cap,
because trend detection needs coverage history.
"""
from __future__ import annotations

from calendar import timegm
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import feedparser
import requests

from agents.trend_detector import publisher_from_feed

TIMEOUT_SECONDS = 12
USER_AGENT = "ElinityTrending/1.1 (+RSS trend monitoring)"
MAX_ENTRIES_PER_FEED = 40


class _ImageParser(HTMLParser):
    """Extract the first usable image from RSS summary/content HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.image_url = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "img" or self.image_url:
            return
        attrs = dict(attrs)
        self.image_url = attrs.get("src") or attrs.get("data-src") or attrs.get("data-original")


def _valid_image_url(value: object, base_url: str) -> str | None:
    if not value:
        return None
    value = unescape(str(value).strip())
    if not value:
        return None
    # Ignore common non-image placeholders/data URIs; the browser needs a fetchable URL.
    if value.startswith("data:"):
        return None
    absolute = urljoin(base_url, value)
    try:
        parsed = urlparse(absolute)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return absolute


def _image_from_entry(entry: dict, feed_url: str) -> str | None:
    """Read common RSS/Atom image fields, then fall back to an image in HTML content."""
    # Media RSS: media:content and media:thumbnail (feedparser normalizes these keys).
    for field in ("media_thumbnail", "media_content"):
        values = entry.get(field) or []
        if isinstance(values, dict):
            values = [values]
        for item in values:
            if not isinstance(item, dict):
                continue
            candidate = item.get("url") or item.get("href")
            image = _valid_image_url(candidate, feed_url)
            if image:
                return image

    # RSS enclosure / Atom links. Prefer explicit image MIME types.
    enclosures = entry.get("enclosures") or []
    for item in enclosures:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("type") or "").lower()
        candidate = item.get("href") or item.get("url")
        if mime.startswith("image/") or any(str(candidate or "").lower().split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
            image = _valid_image_url(candidate, feed_url)
            if image:
                return image

    for item in entry.get("links") or []:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("type") or "").lower()
        rel = str(item.get("rel") or "").lower()
        candidate = item.get("href") or item.get("url")
        if mime.startswith("image/") or (rel == "enclosure" and candidate):
            image = _valid_image_url(candidate, feed_url)
            if image:
                return image

    # Some feeds only include the thumbnail inside summary/content HTML.
    html_parts = []
    if entry.get("summary"):
        html_parts.append(str(entry.get("summary")))
    for content_item in entry.get("content") or []:
        if isinstance(content_item, dict) and content_item.get("value"):
            html_parts.append(str(content_item["value"]))
    for html in html_parts:
        parser = _ImageParser()
        try:
            parser.feed(html)
        except Exception:
            continue
        image = _valid_image_url(parser.image_url, feed_url)
        if image:
            return image
    return None


def _published(entry: dict) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
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
                "image_url": _image_from_entry(entry, feed_url),
            })

    image_count = sum(1 for article in articles if article.get("image_url"))
    print(f"📰 Trending collector fetched {len(articles)} unique RSS articles from {len(sources)} feeds; {image_count} have image URLs.")
    return articles
