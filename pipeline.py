from urllib.parse import urlparse

from storage import (
    insert_news_cache,
    clear_news_cache,
    get_all_sources,
    get_users_with_email,
    get_news_from_user_sources,
)

from agents.news_collector import fetch_from_rss_sources
from agents.headline_generator import generate_headline, generate_ai_summary
from agents.email_sender import send_email


def _valid_http_url(value):
    """Return a usable HTTP(S) URL, otherwise None."""
    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None

    return value


def _has_image(item):
    return _valid_http_url(item.get("image_url")) is not None


def _log_image(stage, item):
    """Log image presence and URL without exposing credentials."""
    title = str(
        item.get("title")
        or item.get("original_title")
        or item.get("ai_headline")
        or item.get("headline")
        or "Untitled"
    )[:90]

    image_url = _valid_http_url(item.get("image_url"))
    if image_url:
        print(f"🖼️ {stage}: FOUND | {title}")
        print(f"   URL: {image_url}")
    else:
        print(f"🖼️ {stage}: NULL/INVALID | {title}")


def build_news_cache():
    print("🧹 Clearing old cache...")
    try:
        clear_news_cache()
    except Exception as exc:
        print(f"❌ Cache clear failed: {type(exc).__name__}: {exc}")
        return 0

    print("🌐 Fetching RSS sources from DB...")
    try:
        sources = get_all_sources()
    except Exception as exc:
        print(f"❌ Could not load RSS sources: {type(exc).__name__}: {exc}")
        return 0

    if not sources:
        print("⚠️ No RSS sources found in DB.")
        return 0

    # Preserve each URL/category combination when a feed belongs to multiple categories.
    source_map = {}
    for source in sources:
        rss_url = source.get("rss_url")
        category = source.get("category") or "General"
        if rss_url:
            source_map[(rss_url, category)] = {
                "rss_url": rss_url,
                "category": category,
            }

    unique_sources = list(source_map.values())
    print(f"📡 Fetching from {len(unique_sources)} unique feed/category pairs...")

    try:
        articles = fetch_from_rss_sources(unique_sources)
    except Exception as exc:
        print(f"❌ RSS collection failed: {type(exc).__name__}: {exc}")
        return 0

    if not articles:
        print("⚠️ Collector returned zero articles.")
        return 0

    collector_images = sum(1 for article in articles if _has_image(article))
    print(
        f"🖼️ Collector supplied valid image URLs for "
        f"{collector_images}/{len(articles)} articles."
    )

    processed = 0
    for article in articles:
        _log_image("PIPELINE RECEIVED IMAGE", article)

        try:
            ai_headline = generate_headline(article)
            ai_summary = generate_ai_summary(article)
            # insert_news_cache should persist article['image_url'] into news_cache.image_url.
            insert_news_cache(article, ai_headline, ai_summary)
            processed += 1
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:90]
            print(
                f"❌ Article processing/storage failed for {title}: "
                f"{type(exc).__name__}: {exc}"
            )

    print(f"✅ News cache built: {processed}/{len(articles)} articles stored.")
    return processed


def run_pipeline():
    print("🚀 NEWS PIPELINE VERSION: normal-email-delivery-2026-10-17")

    try:
        users = get_users_with_email()
    except Exception as exc:
        print(f"❌ Could not load users: {type(exc).__name__}: {exc}")
        return

    if not users:
        print("⚠️ No Auth users with email addresses found.")
        return

    stored_count = build_news_cache()
    if stored_count == 0:
        print("⚠️ No articles were stored; email will not be sent.")
        return

    emails_sent = 0
    emails_failed = 0

    for user in users:
        user_email = (user.get("email") or "").strip()
        user_id = user.get("user_id")

        if not user_email:
            print(f"⚠️ Skipping user {user_id or '(unknown ID)'}: no email address.")
            continue

        print(f"\n📰 Preparing personalized digest for: {user_email}")

        try:
            raw_news = get_news_from_user_sources(user_id)
        except Exception as exc:
            print(f"❌ Cached-news retrieval failed for {user_email}: {type(exc).__name__}: {exc}")
            continue

        if not raw_news:
            print(f"⚠️ No cached news matched {user_email}'s selected RSS sources.")
            continue

        headlines = []
        for news in raw_news:
            item = {
                "category": news.get("category") or "General",
                "headline": (
                    news.get("ai_headline")
                    or news.get("original_title")
                    or "Untitled"
                ),
                "summary": news.get("ai_summary") or "",
                "link": news.get("link") or "",
                "source": news.get("source") or "",
                "image_url": _valid_http_url(news.get("image_url")),
            }
            headlines.append(item)
            _log_image("EMAIL PAYLOAD IMAGE", item)

        payload_images = sum(1 for item in headlines if _has_image(item))
        print(
            f"📧 Preparing {len(headlines)} articles for {user_email}; "
            f"{payload_images} have valid image URLs."
        )

        if payload_images == 0:
            print(
                "⚠️ No image URLs reached this email payload. Check the RSS collector, "
                "storage insert, and cached-news retrieval."
            )

        try:
            send_email(to_email=user_email, headlines=headlines)
            emails_sent += 1
        except Exception as exc:
            emails_failed += 1
            print(f"❌ Email failed for {user_email}: {type(exc).__name__}: {exc}")
            # Continue processing other users if this recipient's email fails.

    print(
        f"\n📬 Email delivery finished. Sent: {emails_sent}; "
        f"failed: {emails_failed}."
    )


if __name__ == "__main__":
    run_pipeline()
