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
from agents.article_deduplicator import deduplicate_articles

# TEST MODE: send one personalized digest to this address instead of real users.
TEST_EMAIL = "sudharsanreddy.saragada@gmail.com"
TEST_MODE = True


def _valid_http_url(value):
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
    title = str(
        item.get("title") or item.get("original_title") or
        item.get("ai_headline") or item.get("headline") or "Untitled"
    )[:90]
    image_url = _valid_http_url(item.get("image_url"))
    if image_url:
        print(f"🖼️ {stage}: FOUND | {title}")
        print(f"   URL: {image_url}")
    else:
        print(f"🖼️ {stage}: NULL/INVALID | {title}")


def _merge_category_associations(articles):
    """Deduplicate by content and preserve all category/feed associations."""
    unique_articles, duplicate_groups = deduplicate_articles(articles)
    for article in unique_articles:
        # deduplicate_articles already collects category/source metadata from
        # each matched member. Normalize these fields defensively here.
        categories = article.get("categories") or [article.get("category")]
        sources = article.get("sources") or [article.get("source")]
        article["categories"] = list(dict.fromkeys(
            str(value).strip() for value in categories if value and str(value).strip()
        ))
        article["sources"] = list(dict.fromkeys(
            str(value).strip() for value in sources if value and str(value).strip()
        ))
        if not article.get("category") and article["categories"]:
            article["category"] = article["categories"][0]
        if not article.get("source") and article["sources"]:
            article["source"] = article["sources"][0]
    return unique_articles, duplicate_groups


def build_news_cache():
    # Collect and validate first. If RSS collection fails, retain the current
    # cache instead of clearing it and leaving the dashboard/email empty.
    print("🌐 Fetching RSS sources from DB...")
    try:
        sources = get_all_sources()
    except Exception as exc:
        print(f"❌ Could not load RSS sources: {type(exc).__name__}: {exc}")
        return 0
    if not sources:
        print("⚠️ No RSS sources found in DB; existing cache was left untouched.")
        return 0

    source_map = {}
    for source in sources:
        rss_url = source.get("rss_url")
        category = source.get("category") or "General"
        if rss_url:
            source_map[(rss_url, category)] = {"rss_url": rss_url, "category": category}
    unique_sources = list(source_map.values())
    print(f"📡 Fetching from {len(unique_sources)} unique feed/category pairs...")

    try:
        collected_articles = fetch_from_rss_sources(unique_sources)
    except Exception as exc:
        print(f"❌ RSS collection failed: {type(exc).__name__}: {exc}")
        return 0
    if not collected_articles:
        print("⚠️ Collector returned zero articles; existing cache was left untouched.")
        return 0

    original_count = len(collected_articles)
    articles, duplicate_groups = _merge_category_associations(collected_articles)
    if not articles:
        print("⚠️ Deduplication returned zero articles; existing cache was left untouched.")
        return 0

    print(
        f"🧹 Content deduplication: {original_count} -> {len(articles)} articles; "
        f"{len(duplicate_groups)} duplicate groups. Categories were not used for matching."
    )
    collector_images = sum(1 for article in articles if _has_image(article))
    print(f"🖼️ Collector supplied valid image URLs for {collector_images}/{len(articles)} unique articles.")

    # Only clear after collection and deduplication succeeded.
    try:
        print("🧹 Clearing old cache after successful collection...")
        clear_news_cache()
    except Exception as exc:
        print(f"❌ Cache clear failed: {type(exc).__name__}: {exc}")
        return 0

    processed = 0
    for article in articles:
        _log_image("PIPELINE RECEIVED IMAGE", article)
        try:
            ai_headline = generate_headline(article)
            ai_summary = generate_ai_summary(article)
            insert_news_cache(article, ai_headline, ai_summary)
            processed += 1
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:90]
            print(f"❌ Article processing/storage failed for {title}: {type(exc).__name__}: {exc}")

    print(f"✅ News cache built: {processed}/{len(articles)} unique articles stored.")
    return processed


def run_pipeline():
    print("🚀 NEWS PIPELINE VERSION: content-deduplication-2026-10-20-fix1")
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
    test_email_sent = False
    for user in users:
        if TEST_MODE and test_email_sent:
            break
        user_email = (user.get("email") or "").strip()
        user_id = user.get("user_id")
        if not user_email:
            print(f"⚠️ Skipping user {user_id or '(unknown ID)'}: no email address.")
            continue
        delivery_email = TEST_EMAIL if TEST_MODE else user_email
        print(f"\n📰 Preparing personalized digest for source user: {user_email}")
        if TEST_MODE:
            print(f"🧪 TEST MODE: digest will be sent to {delivery_email}")
        try:
            raw_news = get_news_from_user_sources(user_id)
        except Exception as exc:
            print(f"❌ Cached-news retrieval failed for {user_email}: {type(exc).__name__}: {exc}")
            continue
        if not raw_news:
            print(f"⚠️ No cached news matched {user_email}'s selected RSS sources.")
            continue

        headlines = []
        seen_links = set()
        for news in raw_news:
            link = news.get("link") or ""
            if link and link in seen_links:
                continue
            if link:
                seen_links.add(link)
            item = {
                "category": news.get("category") or "General",
                "headline": news.get("ai_headline") or news.get("original_title") or "Untitled",
                "summary": news.get("ai_summary") or "",
                "link": link,
                "source": news.get("source") or "",
                "image_url": _valid_http_url(news.get("image_url")),
            }
            headlines.append(item)
            _log_image("EMAIL PAYLOAD IMAGE", item)

        payload_images = sum(1 for item in headlines if _has_image(item))
        print(f"📧 Preparing {len(headlines)} articles; {payload_images} have valid image URLs.")
        try:
            send_email(to_email=delivery_email, headlines=headlines)
            emails_sent += 1
            if TEST_MODE:
                test_email_sent = True
        except Exception as exc:
            emails_failed += 1
            print(f"❌ Email failed for {delivery_email}: {type(exc).__name__}: {exc}")

    print(f"\n📬 Email delivery finished. Sent: {emails_sent}; failed: {emails_failed}.")


if __name__ == "__main__":
    run_pipeline()
