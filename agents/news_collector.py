import calendar
import re
import time
from html import unescape
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup


feedparser.USER_AGENT = "AI-News-Agent/1.1 (+RSS image extraction)"
RECENCY_WEIGHT = 0.5
POPULARITY_WEIGHT = 0.5
REQUEST_TIMEOUT = 10
READER_TIMEOUT = 25
MAX_ARTICLES_PER_FEED = 10
MAX_IMAGE_LOOKUPS = 60
MAX_WIKIMEDIA_LOOKUPS = 30
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _valid_image_url(url, base_url=None):
    """Normalize a candidate image URL; reject non-HTTP(S) values."""
    if not url:
        return None

    url = unescape(str(url).strip()).strip("\"'")
    if not url:
        return None

    if base_url:
        url = urljoin(base_url, url)
    elif url.startswith("//"):
        url = "https:" + url

    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None

    if parsed.username or parsed.password:
        return None

    return url


def _first_srcset_url(srcset):
    """Choose the highest-width candidate from an HTML srcset."""
    if not srcset:
        return None

    candidates = []
    for candidate in srcset.split(","):
        parts = candidate.strip().split()
        if not parts:
            continue

        score = 0
        if len(parts) > 1:
            descriptor = parts[1].lower()
            try:
                if descriptor.endswith("w"):
                    score = int(descriptor[:-1])
                elif descriptor.endswith("x"):
                    score = int(float(descriptor[:-1]) * 1000)
            except ValueError:
                pass
        candidates.append((score, parts[0]))

    return max(candidates, default=(0, None))[1]


def _extract_image(entry):
    """
    Extract an image from RSS/Atom metadata and embedded feed HTML.
    This function does not need to request the article page.
    """
    # 1. Media RSS image metadata.
    for field in ("media_content", "media_thumbnail"):
        values = entry.get(field, []) or []
        if isinstance(values, dict):
            values = [values]
        for media in values:
            if not isinstance(media, dict):
                continue
            media_type = (media.get("type") or "").lower()
            medium = (media.get("medium") or "").lower()
            candidate = media.get("url") or media.get("href")
            if candidate and (
                media_type.startswith("image/")
                or medium == "image"
                or field == "media_thumbnail"
                or not media_type
            ):
                result = _valid_image_url(candidate)
                if result:
                    return result

    # 2. RSS enclosures.
    for enclosure in entry.get("enclosures", []) or []:
        if not isinstance(enclosure, dict):
            continue
        candidate = enclosure.get("href") or enclosure.get("url")
        mime = (enclosure.get("type") or "").lower()
        if candidate and (mime.startswith("image/") or not mime):
            result = _valid_image_url(candidate)
            if result:
                return result

    # 3. Atom links with image MIME types.
    for link in entry.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        rel = (link.get("rel") or "").lower()
        mime = (link.get("type") or "").lower()
        candidate = link.get("href")
        if candidate and rel == "enclosure" and mime.startswith("image/"):
            result = _valid_image_url(candidate)
            if result:
                return result

    # 4. Entry-level image objects.
    image = entry.get("image")
    if isinstance(image, dict):
        candidate = image.get("href") or image.get("url")
        result = _valid_image_url(candidate)
        if result:
            return result
    elif isinstance(image, str):
        result = _valid_image_url(image)
        if result:
            return result

    # 5. Images inside content, summary, description, or encoded content.
    html_fields = []
    for block in entry.get("content", []) or []:
        if isinstance(block, dict):
            html_fields.append(block.get("value", ""))
    for field in ("summary", "description", "summary_detail", "content_encoded"):
        value = entry.get(field, "")
        if isinstance(value, dict):
            value = value.get("value", "")
        if value:
            html_fields.append(value)

    for html in html_fields:
        if not html:
            continue
        soup = BeautifulSoup(str(html), "html.parser")

        # Prefer common lazy-loaded image attributes and srcset.
        for img in soup.find_all("img"):
            candidate = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("data-url")
                or img.get("data-orig-file")
                or _first_srcset_url(img.get("srcset"))
            )
            result = _valid_image_url(candidate)
            if result:
                return result

        # Some feeds provide the image only as a linked URL.
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if re.search(r"\.(?:jpe?g|png|webp|gif|avif)(?:[?#].*)?$", href, re.I):
                result = _valid_image_url(href)
                if result:
                    return result

    # 6. Some publishers use a thumbnail field not normalized by feedparser.
    for key, value in entry.items():
        if "image" in key.lower() or "thumbnail" in key.lower():
            if isinstance(value, str):
                result = _valid_image_url(value)
                if result:
                    return result
            elif isinstance(value, dict):
                result = _valid_image_url(value.get("url") or value.get("href"))
                if result:
                    return result

    return None


def _find_image_in_html(page_html, base_url):
    """Find a likely article image from Open Graph, Twitter, JSON-LD, or HTML."""
    soup = BeautifulSoup(page_html, "html.parser")

    # Social preview metadata is usually the best article thumbnail.
    meta_selectors = [
        ("property", "og:image"),
        ("property", "og:image:url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
        ("itemprop", "image"),
    ]
    for attribute, value in meta_selectors:
        for tag in soup.find_all("meta", attrs={attribute: value}):
            candidate = tag.get("content")
            result = _valid_image_url(candidate, base_url)
            if result:
                return result

    image_link = soup.find("link", attrs={"rel": "image_src"})
    if image_link:
        result = _valid_image_url(image_link.get("href"), base_url)
        if result:
            return result

    # JSON-LD article image.
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            import json
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        def walk_json(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.lower() in ("image", "thumbnailurl"):
                        candidates = child if isinstance(child, list) else [child]
                        for candidate in candidates:
                            if isinstance(candidate, dict):
                                candidate = candidate.get("url") or candidate.get("contentUrl")
                            result = _valid_image_url(candidate, base_url) if isinstance(candidate, str) else None
                            if result:
                                return result
                    result = walk_json(child)
                    if result:
                        return result
            elif isinstance(value, list):
                for child in value:
                    result = walk_json(child)
                    if result:
                        return result
            return None

        result = walk_json(data)
        if result:
            return result

    article_body = soup.find("article") or soup.find("main")
    scopes = [article_body, soup] if article_body else [soup]
    for scope in scopes:
        for img in scope.find_all("img"):
            candidate = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("data-url")
                or _first_srcset_url(img.get("srcset"))
            )
            result = _valid_image_url(candidate, base_url)
            if result:
                return result

    return None


def extract_article_image(article_url):
    """Try publisher HTML and then Jina Reader; return None if both fail."""
    if not article_url:
        return None

    article_url = _valid_image_url(article_url)
    if not article_url:
        return None

    # Direct request; some publishers block automated access with 403.
    try:
        response = requests.get(
            article_url,
            headers=HTTP_HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        if "html" in response.headers.get("Content-Type", "").lower():
            image_url = _find_image_in_html(response.text, response.url)
            if image_url:
                print(f"🖼️ Article-page image found: {image_url}")
                return image_url
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 403:
            print(f"⚠️ Publisher blocked article image lookup (403): {article_url}")
        else:
            print(f"⚠️ Article image lookup failed ({type(exc).__name__}): {article_url}")

    # Reader fallback. It can also fail or be rate-limited; RSS extraction remains first.
    try:
        reader_url = "https://r.jina.ai/" + article_url
        response = requests.get(
            reader_url,
            headers={
                "X-Respond-With": "html",
                "X-Retain-Images": "html",
                "User-Agent": "AI-News-Agent/1.1",
            },
            timeout=READER_TIMEOUT,
        )
        response.raise_for_status()

        image_url = _find_image_in_html(response.text, article_url)
        if image_url:
            print(f"🖼️ Reader fallback image found: {image_url}")
            return image_url

        # Some reader responses represent images as Markdown.
        for candidate in re.findall(
            r"!\[[^\]]*\]\((https?://[^)\s]+)",
            response.text,
        ):
            result = _valid_image_url(candidate, article_url)
            if result:
                print(f"🖼️ Reader Markdown image found: {result}")
                return result

    except requests.RequestException as exc:
        print(f"⚠️ Reader fallback failed ({type(exc).__name__}): {article_url}")

    return None


def _get_article_image(entry):
    """Prefer RSS metadata; only request the article page if RSS has no image."""
    image_url = _extract_image(entry)
    if image_url:
        return image_url

    return extract_article_image(entry.get("link", ""))


def search_wikimedia_image(query):
    """Find a likely Wikimedia Commons thumbnail without an API key.

    Returns (image_url, license_name, attribution) or (None, None, None).
    Search results are only illustrative candidates; callers should not treat
    them as the exact image published by the news outlet.
    """
    query = unescape(str(query or "")).strip()
    if not query:
        return None, None, None

    # Keep queries focused; very long article headlines are noisy.
    query = " ".join(query.split())[:180]
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,  # File namespace only
        "gsrlimit": 8,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 640,
        "format": "json",
    }
    headers = {
        "User-Agent": "AI-News-Agent/1.2 (Wikimedia Commons image search; contact: project maintainer)"
    }

    try:
        response = requests.get(
            WIKIMEDIA_API_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"⚠️ Wikimedia image search failed ({type(exc).__name__}): {query[:80]}")
        return None, None, None

    pages = payload.get("query", {}).get("pages", {})
    # API generator search results are ordered by relevance.
    for page in pages.values():
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        image_url = _valid_image_url(info.get("thumburl") or info.get("url"))
        if not image_url:
            continue

        # Avoid vector/document files as email thumbnails.
        title = str(page.get("title", "")).lower()
        if title.endswith((".svg", ".pdf", ".djvu", ".ogg", ".ogv")):
            continue

        metadata = info.get("extmetadata") or {}
        license_name = (metadata.get("LicenseShortName") or {}).get("value", "")
        attribution = (metadata.get("Artist") or {}).get("value", "")
        attribution = BeautifulSoup(attribution, "html.parser").get_text(" ", strip=True)

        print(
            "🖼️ Wikimedia fallback found: "
            f"{image_url} | file={page.get('title', 'unknown')} | "
            f"license={license_name or 'check file page'}"
        )
        return image_url, license_name or None, attribution or None

    print(f"🖼️ Wikimedia fallback found no image: {query[:80]}")
    return None, None, None


def _entry_timestamp(entry):
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        try:
            return float(calendar.timegm(published))
        except (TypeError, ValueError, OverflowError):
            pass
    return 0.0


def _entry_popularity(entry):
    for value in (
        entry.get("slash_comments"),
        entry.get("comment_count"),
        entry.get("comments"),
        entry.get("views"),
    ):
        if value is None:
            continue
        try:
            return max(0, int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return 0


def _normalize_source(source):
    """Accept a source dictionary and normalize its required fields."""
    if not isinstance(source, dict):
        return None

    rss_url = source.get("rss_url")
    category = source.get("category")
    if not rss_url or not category:
        return None

    return {"rss_url": str(rss_url).strip(), "category": str(category).strip()}


def fetch_from_rss_sources(sources):
    """
    Fetch articles from RSS feeds.

    Returned dictionaries include:
      title, link, summary, source, category, published_at, image_url

    RSS image metadata is always checked first. Article-page requests are
    attempted only when no image is present in the feed metadata.
    """
    if not sources:
        print("⚠️ No RSS sources supplied to collector.")
        return []

    normalized_sources = []
    seen_sources = set()
    for source in sources:
        normalized = _normalize_source(source)
        if not normalized:
            print(f"⚠️ Skipping invalid source entry: {source!r}")
            continue
        key = (normalized["rss_url"], normalized["category"])
        if key not in seen_sources:
            seen_sources.add(key)
            normalized_sources.append(normalized)

    articles = []
    seen_links = set()
    image_lookups = 0
    rss_image_count = 0
    article_page_image_count = 0
    wikimedia_image_count = 0
    wikimedia_lookups = 0

    for source in normalized_sources:
        feed_url = source["rss_url"]
        category = source["category"]
        print(f"📥 Reading feed: {feed_url} [{category}]")

        try:
            response = requests.get(
                feed_url,
                headers=HTTP_HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            print(f"⚠️ RSS fetch failed ({type(exc).__name__}): {feed_url}")
            continue
        except Exception as exc:
            print(f"⚠️ RSS parse failed ({type(exc).__name__}): {feed_url}")
            continue

        if not feed.entries:
            print(f"⚠️ Feed returned no entries: {feed_url}")
            continue

        feed_article_count = 0
        for entry in feed.entries:
            # Keep at most 10 unique articles from each individual RSS feed.
            # Apply the cap per feed URL/category association, not per category.
            if feed_article_count >= MAX_ARTICLES_PER_FEED:
                break

            link = entry.get("link", "")
            title = unescape(str(entry.get("title") or "Untitled")).strip()
            # Keep the same article once per category association. The shared
            # content deduplicator later merges these into one article while
            # preserving all categories and source feeds.
            link_key = (link.strip(), category.casefold()) if link else None
            if link_key and link_key in seen_links:
                continue

            # First pass: RSS fields only. This is the cheapest and most reliable
            # way to obtain image URLs when the publisher provides them.
            image_url = _extract_image(entry)
            image_source = "rss" if image_url else None
            image_license = None
            image_attribution = None
            if image_url:
                rss_image_count += 1
            elif link and image_lookups < MAX_IMAGE_LOOKUPS:
                image_lookups += 1
                image_url = extract_article_image(link)
                if image_url:
                    image_source = "article_page"
                    article_page_image_count += 1

            summary_html = entry.get("summary", "") or entry.get("description", "") or ""
            summary = BeautifulSoup(str(summary_html), "html.parser").get_text(
                " ", strip=True
            )
            summary = unescape(summary).strip()

            # Final no-key fallback: search Wikimedia Commons by headline and
            # a small amount of summary context. Bound requests to protect the
            # scheduled workflow from excessive external API calls.
            if not image_url and wikimedia_lookups < MAX_WIKIMEDIA_LOOKUPS:
                wikimedia_lookups += 1
                # Search by headline first; adding the full summary often makes
                # Commons' text search too restrictive and less relevant.
                image_url, image_license, image_attribution = search_wikimedia_image(title)
                if image_url:
                    image_source = "wikimedia_commons"
                    wikimedia_image_count += 1

            published_ts = _entry_timestamp(entry)
            published_at = (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(published_ts))
                if published_ts
                else None
            )

            article = {
                "title": title,
                "link": link,
                "summary": summary,
                "source": feed_url,
                "category": category,
                "published_at": published_at,
                "published_timestamp": published_ts,
                "popularity": _entry_popularity(entry),
                "image_url": image_url,
                "image_source": image_source,
                "image_license": image_license,
                "image_attribution": image_attribution,
            }

            print(
                f"🖼️ COLLECTOR IMAGE: {'FOUND' if image_url else 'NULL'} | "
                f"{title[:90]}"
            )
            if image_url:
                print(f"   URL: {image_url}")

            articles.append(article)
            if link_key:
                seen_links.add(link_key)
            feed_article_count += 1

        print(
            f"📄 Collected {feed_article_count} unique articles from this feed "
            f"(limit: {MAX_ARTICLES_PER_FEED})."
        )

    if image_lookups >= MAX_IMAGE_LOOKUPS:
        print(
            f"ℹ️ Reached article-page image lookup limit ({MAX_IMAGE_LOOKUPS}); "
            "remaining articles will skip article-page lookups; Wikimedia fallback "
            "may still run within its separate limit."
        )

    # Rank all collected articles by recency and popularity.
    # Do not cap articles per category: every linked RSS feed can contribute.
    now = time.time()
    timestamps = [
        article["published_timestamp"]
        for article in articles
        if article["published_timestamp"] > 0
    ]
    oldest = min(timestamps) if timestamps else now - 30 * 86400
    newest = max(timestamps) if timestamps else now
    max_popularity = max(
        (article["popularity"] for article in articles),
        default=0,
    )

    for article in articles:
        ts = article["published_timestamp"]
        if ts > 0 and newest > oldest:
            recency_score = (ts - oldest) / (newest - oldest)
        elif ts > 0:
            recency_score = 1.0
        else:
            recency_score = 0.0

        popularity_score = (
            article["popularity"] / max_popularity
            if max_popularity > 0
            else 0.0
        )
        article["score"] = (
            RECENCY_WEIGHT * recency_score
            + POPULARITY_WEIGHT * popularity_score
        )

    articles.sort(key=lambda item: item["score"], reverse=True)

    selected_images = sum(1 for article in articles if article.get("image_url"))
    print(
        f"🖼️ Image summary: {selected_images}/{len(articles)} articles "
        f"have image URLs (RSS: {rss_image_count}, article-page fallback: "
        f"{article_page_image_count}, Wikimedia: {wikimedia_image_count}; "
        f"Wikimedia searches: {wikimedia_lookups})."
    )
    print(
        f"✅ Collector returning {len(articles)} articles "
        f"from {len(normalized_sources)} feeds."
    )

    return articles
