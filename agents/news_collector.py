
import feedparser
import time
import re
import calendar
import requests

from html import unescape
from collections import defaultdict
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup


# -------------------------------
# CONFIG
# -------------------------------
feedparser.USER_AGENT = "AI-News-Agent/1.0 (+https://example.com)"

MAX_ARTICLES_PER_CATEGORY = 5
RECENCY_WEIGHT = 0.5
POPULARITY_WEIGHT = 0.5

REQUEST_TIMEOUT = 10

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ElinityNewsBot/1.0)"
    )
}


# -------------------------------
# IMAGE URL VALIDATION
# -------------------------------
def _valid_image_url(url, base_url=None):
    """Return an absolute HTTP/HTTPS image URL, or None."""
    if not url:
        return None

    url = unescape(str(url).strip())

    if base_url:
        url = urljoin(base_url, url)
    elif url.startswith("//"):
        url = "https:" + url

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    return url


# -------------------------------
# IMAGE EXTRACTION FROM RSS
# -------------------------------
def _extract_image(entry):
    """Extract an article image URL from RSS metadata and HTML."""

    # 1. Standard RSS enclosures
    for enclosure in entry.get("enclosures", []):
        image_url = enclosure.get("href") or enclosure.get("url")
        mime_type = enclosure.get("type", "")

        if image_url and (
            mime_type.startswith("image/") or not mime_type
        ):
            image_url = _valid_image_url(image_url)
            if image_url:
                return image_url

    # 2. Media RSS content and thumbnails
    for field in ("media_content", "media_thumbnail"):
        for media in entry.get(field, []):
            image_url = _valid_image_url(media.get("url"))
            if image_url:
                return image_url

    # 3. Image links exposed by Atom/RSS parsers
    for link in entry.get("links", []):
        href = link.get("href", "")
        rel = link.get("rel", "")
        mime_type = link.get("type", "")

        if href and (
            rel == "enclosure" and mime_type.startswith("image/")
        ):
            image_url = _valid_image_url(href)
            if image_url:
                return image_url

    # 4. Image objects sometimes exposed directly by feedparser
    image = entry.get("image")

    if isinstance(image, dict):
        image_url = _valid_image_url(
            image.get("href") or image.get("url")
        )
        if image_url:
            return image_url

    # 5. Images embedded in RSS content or descriptions
    html_fields = [
        content.get("value", "")
        for content in entry.get("content", [])
    ]

    html_fields.extend([
        entry.get("summary", ""),
        entry.get("description", ""),
    ])

    for html in html_fields:
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        # Check common image elements and lazy-loading attributes
        for img in soup.find_all("img"):
            image_url = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("data-url")
            )

            # Use the first URL from srcset if src is unavailable
            if not image_url and img.get("srcset"):
                image_url = img["srcset"].split(",")[0].strip().split()[0]

            if image_url:
                image_url = _valid_image_url(image_url)

                if image_url:
                    return image_url

    return None

# -------------------------------
# IMAGE EXTRACTION FROM ARTICLE PAGE
# -------------------------------
def extract_article_image(article_url):
    """
    Try publisher metadata when the RSS feed has no image.
    Does not download or store the image itself.
    """

    if not article_url:
        return None

    parsed_article = urlparse(article_url)

    if parsed_article.scheme not in ("http", "https"):
        return None

    try:
        response = requests.get(
            article_url,
            headers=HTTP_HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")

        if "html" not in content_type.lower():
            return None

        # Use the final URL after redirects as the base for relative URLs.
        soup = BeautifulSoup(response.text, "html.parser")
        base_url = response.url

        # 1. Open Graph image
        selectors = [
            ("property", "og:image"),
            ("property", "og:image:url"),
            ("name", "twitter:image"),
            ("name", "twitter:image:src"),
        ]

        for attribute, value in selectors:
            tag = soup.find(
                "meta",
                attrs={attribute: value},
            )

            if tag and tag.get("content"):
                image_url = _valid_image_url(
                    tag["content"],
                    base_url,
                )

                if image_url:
                    return image_url

        # 2. First image inside the article body
        article_body = soup.find("article") or soup.find("main")

        if article_body:
            for img in article_body.find_all("img"):
                image_url = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-lazy-src")
                )

                if image_url:
                    image_url = _valid_image_url(
                        image_url,
                        base_url,
                    )

                    if image_url:
                        return image_url

    except requests.RequestException as exc:
        print(f"Image lookup failed [{article_url}]: {exc}")

    except Exception as exc:
        print(f"Could not parse article page [{article_url}]: {exc}")

    return None


# -------------------------------
# GET ARTICLE IMAGE
# -------------------------------
def _get_article_image(entry):
    """
    Prefer RSS images.
    Fetch the article page only when RSS has no image.
    """

    image_url = _extract_image(entry)

    if image_url:
        return image_url

    article_url = entry.get("link", "")

    if article_url:
        return extract_article_image(article_url)

    return None


# -------------------------------
# TIMESTAMP HELPER
# -------------------------------
def _entry_timestamp(entry) -> float:
    published = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )

    if published:
        # RSS parsed dates are UTC.
        return float(calendar.timegm(published))

    return 0.0


# -------------------------------
# POPULARITY HELPER
# -------------------------------
def _entry_popularity(entry) -> int:
    popularity_fields = [
        entry.get("slash_comments"),
        entry.get("comment_count"),
        entry.get("comments"),
        entry.get("views"),
    ]

    for value in popularity_fields:
        if value is None:
            continue

        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue

    return 0


# -------------------------------
# MAIN RSS FETCHER
# -------------------------------
def fetch_from_rss_sources(sources):
    if not sources:
        return []

    articles = []

    # -------------------------------
    # FETCH RSS
    # -------------------------------
    for source in sources:
        feed_url = source["rss_url"]
        category = source["category"]

        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                print(f"Invalid RSS feed: {feed_url}")
                continue

            for entry in feed.entries:
                article_link = entry.get("link", "")

                try:
                    image_url = _get_article_image(entry)
                except Exception as exc:
                    print(
                        f"Image extraction failed "
                        f"[{article_link}]: {exc}"
                    )
                    image_url = None

                articles.append({
                    "category": category,
                    "title": entry.get("title", "Untitled"),
                    "summary": entry.get("summary", ""),
                    "link": article_link,
                    "source": feed_url,
                    "image_url": image_url,
                    "published_ts": _entry_timestamp(entry),
                    "popularity": _entry_popularity(entry),
                })

            time.sleep(1)

        except Exception as exc:
            print(f"RSS failed [{feed_url}]: {exc}")
            continue

    # -------------------------------
    # DEDUPLICATION
    # -------------------------------
    deduped = {}

    for article in articles:
        key = article.get("link") or (
            f"{article['source']}::{article['title']}"
        )

        existing = deduped.get(key)

        if existing is None:
            deduped[key] = article
            continue

        # Preserve the better metadata record.
        preferred = article

        if (
            existing["published_ts"],
            existing["popularity"],
        ) > (
            article["published_ts"],
            article["popularity"],
        ):
            preferred = existing

        # Never discard an available image.
        preferred["image_url"] = (
            preferred.get("image_url")
            or existing.get("image_url")
            or article.get("image_url")
        )

        deduped[key] = preferred

    deduped_values = list(deduped.values())

    if not deduped_values:
        return []

    # -------------------------------
    # SCORING
    # -------------------------------
    max_ts = max(
        (a["published_ts"] for a in deduped_values),
        default=0.0,
    )

    max_pop = max(
        (a["popularity"] for a in deduped_values),
        default=0,
    )

    def _score(article):
        recency_score = (
            article["published_ts"] / max_ts
            if max_ts else 0.0
        )

        popularity_score = (
            article["popularity"] / max_pop
            if max_pop else 0.0
        )

        return (
            RECENCY_WEIGHT * recency_score
            + POPULARITY_WEIGHT * popularity_score
        )

    ranked = sorted(
        deduped_values,
        key=lambda article: (
            _score(article),
            article["published_ts"],
            article["popularity"],
        ),
        reverse=True,
    )

    # -------------------------------
    # BALANCED CATEGORY SELECTION
    # -------------------------------
    category_map = defaultdict(list)

    for article in ranked:
        category_map[article["category"]].append(article)

    final = []

    for category, items in category_map.items():
        source_map = defaultdict(list)

        for item in items:
            source_map[item["source"]].append(item)

        selected = []
        available_sources = list(source_map.keys())

        while (
            len(selected) < MAX_ARTICLES_PER_CATEGORY
            and available_sources
        ):
            # Take one story from each source in turn.
            current_source = available_sources.pop(0)
            source_items = source_map[current_source]

            if source_items:
                selected.append(source_items.pop(0))

            # Sources with remaining articles go to the end.
            if source_items:
                available_sources.append(current_source)

        final.extend(selected)

    return final
