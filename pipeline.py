from urllib.parse import urlparse

from storage import (
    insert_news_cache,
    save_private_news_cache,
    clear_news_cache,
    get_all_sources,
    get_users_with_email,
    get_user_private_sources,
    get_news_from_user_sources,
)
from agents.news_collector import fetch_from_rss_sources
from agents.headline_generator import generate_headline, generate_ai_summary
from agents.email_sender import send_email


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


def _log_image(stage, item):
    title = str(
        item.get("title") or item.get("original_title") or
        item.get("ai_headline") or item.get("headline") or "Untitled"
    )[:90]
    image_url = _valid_http_url(item.get("image_url"))
    print(f"🖼️ {stage}: {'FOUND' if image_url else 'NULL/INVALID'} | {title}")
    if image_url:
        print(f"   URL: {image_url}")


def _unique_source_pairs(sources):
    """Keep one fetch entry per RSS URL/category pair."""
    result = {}
    for source in sources:
        rss_url = source.get("rss_url")
        category = source.get("category") or "General"
        if not rss_url:
            continue
        result[(rss_url, category)] = {**source, "rss_url": rss_url, "category": category}
    return list(result.values())


def build_news_cache():
    """Refresh shared cache from public categories only.

    Collection and AI processing happen before clearing the old cache, so a
    failed RSS fetch does not immediately erase the previous working cache.
    """
    print("🌐 Loading public RSS sources from categories/category_sources/rss...")
    try:
        sources = _unique_source_pairs(get_all_sources())
    except Exception as exc:
        print(f"❌ Could not load public RSS sources: {type(exc).__name__}: {exc}")
        return 0

    if not sources:
        print("⚠️ No public RSS/category associations found; preserving existing cache.")
        return 0

    print(f"📡 Fetching {len(sources)} public RSS/category associations...")
    try:
        articles = fetch_from_rss_sources(sources)
    except Exception as exc:
        print(f"❌ Public RSS collection failed: {type(exc).__name__}: {exc}")
        return 0

    if not articles:
        print("⚠️ Public collector returned no articles; preserving existing cache.")
        return 0

    processed_articles = []
    for index, article in enumerate(articles, start=1):
        _log_image("PUBLIC COLLECTOR IMAGE", article)
        try:
            headline = generate_headline(article)
            summary = generate_ai_summary(article)
            processed_articles.append((article, headline, summary))
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:80]
            print(f"❌ Public AI processing failed for {title}: {type(exc).__name__}: {exc}")

    if not processed_articles:
        print("⚠️ No public articles completed AI processing; preserving existing cache.")
        return 0

    # Replace the public cache only after collection and processing have succeeded.
    try:
        clear_news_cache()
    except Exception as exc:
        print(f"❌ Could not clear old public cache: {type(exc).__name__}: {exc}")
        return 0

    stored = 0
    for article, headline, summary in processed_articles:
        try:
            insert_news_cache(article, headline, summary)
            stored += 1
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:80]
            print(f"❌ Public cache insert failed for {title}: {type(exc).__name__}: {exc}")

    print(f"✅ Shared public cache built: {stored}/{len(processed_articles)} articles stored.")
    return stored


def collect_private_news_for_user(user_id):
    """Collect and store private articles only for their category owner."""
    try:
        sources = _unique_source_pairs(get_user_private_sources(user_id))
    except Exception as exc:
        print(f"❌ Could not load private sources for {user_id}: {type(exc).__name__}: {exc}")
        return 0

    if not sources:
        print(f"ℹ️ User {user_id} has no selected private RSS/category associations.")
        return 0

    print(f"🔒 Fetching {len(sources)} private RSS/category associations for owner {user_id}...")
    try:
        articles = fetch_from_rss_sources(sources)
    except Exception as exc:
        print(f"❌ Private RSS collection failed for {user_id}: {type(exc).__name__}: {exc}")
        return 0

    stored = 0
    for article in articles:
        _log_image("PRIVATE COLLECTOR IMAGE", article)
        try:
            headline = generate_headline(article)
            summary = generate_ai_summary(article)
            save_private_news_cache(user_id, article, headline, summary)
            stored += 1
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:80]
            print(f"❌ Private cache save failed for {title}: {type(exc).__name__}: {exc}")

    print(f"🔒 Saved/updated {stored}/{len(articles)} private articles for owner {user_id}.")
    return stored


def run_pipeline():
    print("🚀 NEWS PIPELINE: public-private-category-routing")
    try:
        users = get_users_with_email()
    except Exception as exc:
        print(f"❌ Could not load users: {type(exc).__name__}: {exc}")
        return

    if not users:
        print("⚠️ No Auth users with email addresses found.")
        return

    public_stored = build_news_cache()
    if public_stored == 0:
        print("⚠️ Public cache was not refreshed. Existing cache is preserved where possible.")

    emails_sent = 0
    emails_failed = 0
    for user in users:
        user_id = user.get("user_id")
        user_email = (user.get("email") or "").strip()
        if not user_id or not user_email:
            continue

        print(f"\n📰 Preparing personalized digest for {user_email}...")
        # Private sources and cache rows are always scoped to this owner.
        collect_private_news_for_user(user_id)

        try:
            raw_news = get_news_from_user_sources(user_id)
        except Exception as exc:
            print(f"❌ News retrieval failed for {user_email}: {type(exc).__name__}: {exc}")
            continue

        if not raw_news:
            print(f"⚠️ No cached news matched {user_email}'s selected sources.")
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

        if not headlines:
            print(f"⚠️ No valid articles for {user_email}.")
            continue

        try:
            send_email(to_email=user_email, headlines=headlines)
            emails_sent += 1
            print(f"✅ Digest sent to {user_email} ({len(headlines)} articles).")
        except Exception as exc:
            emails_failed += 1
            print(f"❌ Email failed for {user_email}: {type(exc).__name__}: {exc}")

    print(f"\n📬 Delivery complete. Sent: {emails_sent}; failed: {emails_failed}.")


if __name__ == "__main__":
    run_pipeline()
