from urllib.parse import urlparse

from storage import (
    insert_news_cache,
    clear_news_cache,
    get_all_sources,
    get_users_with_email,
    get_news_from_user_sources,
    get_user_private_sources,
)

from agents.news_collector import fetch_from_rss_sources
from agents.headline_generator import generate_headline, generate_ai_summary
from agents.email_sender import send_email
from agents.article_deduplicator import deduplicate_articles


# TEST MODE: when enabled, send only one personalized digest
# to TEST_EMAIL instead of sending to all real users.
TEST_EMAIL = "sudharsanreddy.saragada@gmail.com"
TEST_MODE = True


def _valid_http_url(value):
    """Return a valid HTTP(S) URL or None."""
    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    if parsed.scheme.lower() not in ("http", "https"):
        return None

    if not parsed.netloc:
        return None

    return value


def _has_image(item):
    """Check whether an article has a valid image URL."""
    return _valid_http_url(item.get("image_url")) is not None


def _log_image(stage, item):
    """Log image availability for debugging."""
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


def _merge_category_associations(articles):
    """
    Deduplicate articles while preserving category and source associations.

    The deduplicator should merge genuinely duplicate content without
    treating different categories as separate copies of the same article.
    """
    unique_articles, duplicate_groups = deduplicate_articles(articles)

    for article in unique_articles:
        categories = article.get("categories") or [
            article.get("category")
        ]

        sources = article.get("sources") or [
            article.get("source")
        ]

        article["categories"] = list(
            dict.fromkeys(
                str(value).strip()
                for value in categories
                if value and str(value).strip()
            )
        )

        article["sources"] = list(
            dict.fromkeys(
                str(value).strip()
                for value in sources
                if value and str(value).strip()
            )
        )

        if not article.get("category") and article["categories"]:
            article["category"] = article["categories"][0]

        if not article.get("source") and article["sources"]:
            article["source"] = article["sources"][0]

    return unique_articles, duplicate_groups


def build_news_cache():
    """
    Build the shared news cache using public RSS sources only.

    Private category feeds are intentionally excluded from this shared
    cache to avoid exposing private-category articles through global news
    or Trending.
    """
    print("🌐 Fetching public RSS sources from DB...")

    try:
        sources = get_all_sources()
    except Exception as exc:
        print(
            f"❌ Could not load public RSS sources: "
            f"{type(exc).__name__}: {exc}"
        )
        return 0

    if not sources:
        print(
            "⚠️ No public RSS sources found. "
            "Existing cache was left untouched."
        )
        return 0

    source_map = {}

    for source in sources:
        rss_url = _valid_http_url(source.get("rss_url"))
        category = (source.get("category") or "General").strip()

        if not rss_url:
            continue

        key = (rss_url, category.lower())

        source_map[key] = {
            "rss_url": rss_url,
            "category": category,
        }

    unique_sources = list(source_map.values())

    if not unique_sources:
        print(
            "⚠️ No valid public RSS URLs found. "
            "Existing cache was left untouched."
        )
        return 0

    print(
        f"📡 Fetching from {len(unique_sources)} "
        "public feed/category pairs..."
    )

    try:
        collected_articles = fetch_from_rss_sources(unique_sources)
    except Exception as exc:
        print(
            f"❌ Public RSS collection failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return 0

    if not collected_articles:
        print(
            "⚠️ Collector returned zero articles. "
            "Existing cache was left untouched."
        )
        return 0

    original_count = len(collected_articles)

    articles, duplicate_groups = _merge_category_associations(
        collected_articles
    )

    if not articles:
        print(
            "⚠️ Deduplication returned zero articles. "
            "Existing cache was left untouched."
        )
        return 0

    print(
        f"🧹 Content deduplication: {original_count} -> "
        f"{len(articles)} unique articles; "
        f"{len(duplicate_groups)} duplicate groups."
    )

    collector_images = sum(
        1 for article in articles if _has_image(article)
    )

    print(
        f"🖼️ Collector supplied valid image URLs for "
        f"{collector_images}/{len(articles)} unique articles."
    )

    # Only clear the existing cache after collection and deduplication
    # have succeeded.
    try:
        print("🧹 Clearing old shared cache after successful collection...")
        clear_news_cache()
    except Exception as exc:
        print(
            f"❌ Cache clear failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return 0

    processed = 0

    for article in articles:
        _log_image("PIPELINE RECEIVED IMAGE", article)

        try:
            ai_headline = generate_headline(article)
            ai_summary = generate_ai_summary(article)

            insert_news_cache(
                article,
                ai_headline,
                ai_summary,
            )

            processed += 1

        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:90]

            print(
                f"❌ Article processing/storage failed for "
                f"{title}: {type(exc).__name__}: {exc}"
            )

    print(
        f"✅ Shared news cache built: "
        f"{processed}/{len(articles)} unique articles stored."
    )

    return processed


def collect_private_news_for_user(user_id):
    """
    Collect and process private feeds selected by their owner.

    These articles are returned for that user's digest only. They are
    not inserted into the shared news cache.
    """
    try:
        sources = get_user_private_sources(user_id)
    except Exception as exc:
        print(
            f"❌ Could not load private feeds for {user_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return []

    if not sources:
        print(
            f"🔒 No owned private feeds selected by user {user_id}."
        )
        return []

    # Deduplicate identical feed/category pairs.
    source_map = {}

    for source in sources:
        rss_url = _valid_http_url(source.get("rss_url"))
        category = (source.get("category") or "General").strip()

        if not rss_url:
            continue

        source_map[(rss_url, category.lower())] = {
            "rss_url": rss_url,
            "category": category,
        }

    sources = list(source_map.values())

    if not sources:
        return []

    print(
        f"🔒 Collecting {len(sources)} private feed/category "
        f"pair(s) for owner {user_id}."
    )

    try:
        collected = fetch_from_rss_sources(sources)
    except Exception as exc:
        print(
            f"❌ Private RSS collection failed for {user_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return []

    if not collected:
        print(
            f"⚠️ Private RSS collector returned no articles "
            f"for user {user_id}."
        )
        return []

    articles, duplicate_groups = _merge_category_associations(
        collected
    )

    print(
        f"🔒 Private articles after deduplication: {len(articles)}; "
        f"duplicate groups: {len(duplicate_groups)}."
    )

    headlines = []

    for article in articles:
        _log_image("PRIVATE ARTICLE IMAGE", article)

        try:
            ai_headline = generate_headline(article)
            ai_summary = generate_ai_summary(article)

            item = {
                "category": article.get("category") or "General",
                "headline": (
                    ai_headline
                    or article.get("title")
                    or "Untitled"
                ),
                "summary": ai_summary or "",
                "link": article.get("link") or "",
                "source": article.get("source") or "",
                "image_url": _valid_http_url(
                    article.get("image_url")
                ),
            }

            headlines.append(item)

        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:90]

            print(
                f"❌ Private article processing failed for "
                f"{title}: {type(exc).__name__}: {exc}"
            )

    print(
        f"🔒 Prepared {len(headlines)} private articles "
        f"for owner {user_id}."
    )

    return headlines


def run_pipeline():
    """Build the shared cache and send personalized digests."""
    print(
        "🚀 NEWS PIPELINE VERSION: "
        "selected-category-cache-top-five-per-rss-2026-10-23"
    )

    try:
        users = get_users_with_email()
    except Exception as exc:
        print(
            f"❌ Could not load users: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    if not users:
        print("⚠️ No Auth users with email addresses found.")
        return

    # Build shared public cache first.
    stored_count = build_news_cache()

    if stored_count == 0:
        print(
            "⚠️ No public articles were stored. "
            "Personalized digests will still be attempted "
            "using owner-only private feeds."
        )

    emails_sent = 0
    emails_failed = 0
    test_email_sent = False

    for user in users:
        if TEST_MODE and test_email_sent:
            break

        user_email = (user.get("email") or "").strip()
        user_id = user.get("user_id")

        if not user_email or not user_id:
            print(
                "⚠️ Skipping user: missing user ID or email address."
            )
            continue

        delivery_email = TEST_EMAIL if TEST_MODE else user_email

        print(
            f"\n📰 Preparing personalized digest for source user: "
            f"{user_email}"
        )

        if TEST_MODE:
            print(
                f"🧪 TEST MODE: digest will be sent to "
                f"{delivery_email}"
            )

        # Retrieve public/shared cached news for selected sources.
        try:
            raw_news = get_news_from_user_sources(user_id)
        except Exception as exc:
            print(
                f"❌ Cached-news retrieval failed for {user_email}: "
                f"{type(exc).__name__}: {exc}"
            )
            raw_news = []

        headlines = []
        seen_links = set()

        for news in raw_news:
            link = (news.get("link") or "").strip()

            if link and link in seen_links:
                continue

            if link:
                seen_links.add(link)

            item = {
                "category": news.get("category") or "General",
                "headline": (
                    news.get("ai_headline")
                    or news.get("original_title")
                    or "Untitled"
                ),
                "summary": news.get("ai_summary") or "",
                "link": link,
                "source": news.get("source") or "",
                "image_url": _valid_http_url(
                    news.get("image_url")
                ),
            }

            headlines.append(item)

        # Selected public and private feeds are retrieved from the caches by
        # get_news_from_user_sources(). Do not fetch private RSS feeds again here;
        # that would bypass the per-RSS top-five cache selection.

        if not headlines:
            print(
                f"⚠️ No cached public or collected private articles "
                f"matched {user_email}'s selected sources."
            )
            continue

        for item in headlines:
            _log_image("EMAIL PAYLOAD IMAGE", item)

        payload_images = sum(
            1 for item in headlines if _has_image(item)
        )

        print(
            f"📧 Preparing {len(headlines)} articles; "
            f"{payload_images} have valid image URLs."
        )

        try:
            send_email(
                to_email=delivery_email,
                headlines=headlines,
            )

            emails_sent += 1

            if TEST_MODE:
                test_email_sent = True

        except Exception as exc:
            emails_failed += 1

            print(
                f"❌ Email failed for {delivery_email}: "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        f"\n📬 Email delivery finished. "
        f"Sent: {emails_sent}; failed: {emails_failed}."
    )


if __name__ == "__main__":
    run_pipeline()
