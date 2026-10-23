"""Build public/private news caches and deliver personalized email digests.

TEST_MODE=True sends one test digest to TEST_EMAIL using public-category news.
Set TEST_MODE=False to send digests to registered users.

Routing rules:
- Public category RSS associations -> news_cache
- Private category RSS associations -> private_news_cache for category owner
- Private collection does not depend on user_category_sources selections.
"""
from collections import defaultdict
from urllib.parse import urlparse

from storage import (
    insert_news_cache,
    save_private_news_cache,
    clear_news_cache,
    get_all_sources,
    get_all_private_sources,
    get_users_with_email,
    get_news_from_user_sources,
    get_cached_news_for_categories,
)
from agents.news_collector import fetch_from_rss_sources
from agents.headline_generator import generate_headline, generate_ai_summary
from agents.email_sender import send_email


# ==================== TEST CONFIGURATION ====================
TEST_MODE = True
TEST_EMAIL = "sudharsanreddy.saragada@gmail.com"
EMAIL_ARTICLES_PER_SOURCE = 10
# ===========================================================


def _valid_http_url(value):
    if not isinstance(value, str) or not value.strip():
        return None

    value = value.strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    return value


def _unique_source_pairs(sources):
    """Deduplicate identical associations without losing category/owner links."""
    result = {}

    for source in sources or []:
        rss_url = _valid_http_url(source.get("rss_url"))
        category = str(source.get("category") or "General").strip()
        if not rss_url:
            continue

        key = (
            rss_url,
            source.get("category_id"),
            category.casefold(),
            source.get("visibility"),
            source.get("owner_id"),
        )
        result[key] = {**source, "rss_url": rss_url, "category": category}

    return list(result.values())


def _process_articles(articles, label):
    """Generate AI headline/summary for each collected article."""
    processed = []

    for article in articles or []:
        title = str(article.get("title") or article.get("original_title") or "Untitled")[:90]
        image_url = _valid_http_url(article.get("image_url"))
        print(f"🖼️ {label} IMAGE: {'FOUND' if image_url else 'NULL/INVALID'} | {title}")
        if image_url:
            print(f"   URL: {image_url}")

        try:
            headline = generate_headline(article)
            summary = generate_ai_summary(article)
            processed.append((article, headline, summary))
        except Exception as exc:
            print(
                f"❌ {label} AI processing failed for {title}: "
                f"{type(exc).__name__}: {exc}"
            )

    return processed


def build_news_cache():
    """Collect every public category/feed association into the shared cache."""
    print("🌐 Loading public RSS sources from categories/category_sources/rss...")

    try:
        sources = _unique_source_pairs(get_all_sources())
    except Exception as exc:
        print(f"❌ Could not load public RSS sources: {type(exc).__name__}: {exc}")
        return 0, []

    # Fail closed: private rows must never be written to the shared cache.
    sources = [source for source in sources if source.get("visibility") == "public"]
    if not sources:
        print("⚠️ No public RSS/category associations found; preserving existing cache.")
        return 0, []

    categories = sorted({source["category"] for source in sources})
    print(f"📡 Fetching {len(sources)} public RSS/category associations...")

    try:
        articles = fetch_from_rss_sources(sources)
    except Exception as exc:
        print(f"❌ Public RSS collection failed: {type(exc).__name__}: {exc}")
        return 0, categories

    if not articles:
        print("⚠️ Public collector returned no articles; preserving existing cache.")
        return 0, categories

    processed = _process_articles(articles, "PUBLIC")
    if not processed:
        print("⚠️ No public articles completed AI processing; preserving existing cache.")
        return 0, categories

    # Clear only after successful collection and processing.
    try:
        clear_news_cache()
    except Exception as exc:
        print(f"❌ Could not clear old public cache: {type(exc).__name__}: {exc}")
        return 0, categories

    stored = 0
    for article, headline, summary in processed:
        try:
            insert_news_cache(article, headline, summary)
            stored += 1
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:80]
            print(f"❌ Public cache insert failed for {title}: {type(exc).__name__}: {exc}")

    print(f"✅ Shared public cache built: {stored}/{len(processed)} articles stored.")
    return stored, categories


def collect_private_news():
    """Collect every private category/feed association and save by category owner."""
    print("\n🔒 Loading all private category RSS associations...")

    try:
        sources = _unique_source_pairs(get_all_private_sources())
    except Exception as exc:
        print(f"❌ Could not load private RSS sources: {type(exc).__name__}: {exc}")
        return 0

    sources = [
        source for source in sources
        if source.get("visibility") == "private" and source.get("owner_id")
    ]
    if not sources:
        print("ℹ️ No private category RSS associations found.")
        return 0

    sources_by_owner = defaultdict(list)
    for source in sources:
        sources_by_owner[str(source["owner_id"])].append(source)

    total_stored = 0
    for owner_id, owner_sources in sources_by_owner.items():
        print(
            f"\n🔒 Owner {owner_id}: fetching "
            f"{len(owner_sources)} private category/feed associations..."
        )

        try:
            articles = fetch_from_rss_sources(owner_sources)
        except Exception as exc:
            print(
                f"❌ Private collection failed for owner {owner_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        if not articles:
            print(f"⚠️ No articles returned for private owner {owner_id}.")
            continue

        processed = _process_articles(articles, "PRIVATE")
        owner_stored = 0
        for article, headline, summary in processed:
            try:
                save_private_news_cache(owner_id, article, headline, summary)
                owner_stored += 1
            except Exception as exc:
                title = str(article.get("title") or "Untitled")[:80]
                print(
                    f"❌ Private cache save failed for {title}: "
                    f"{type(exc).__name__}: {exc}"
                )

        total_stored += owner_stored
        print(
            f"🔒 Owner {owner_id}: saved/updated "
            f"{owner_stored}/{len(processed)} private articles."
        )

    print(f"✅ Total private articles saved/updated: {total_stored}")
    return total_stored


def _prepare_email_articles(raw_news):
    """Normalize cached rows and deduplicate repeated article links."""
    headlines = []
    seen_links = set()

    for news in raw_news or []:
        link = (news.get("link") or "").strip()
        category_key = str(news.get("category") or "General").strip().casefold()
        source_key = str(news.get("source") or "").strip().casefold()
        dedupe_key = (link, category_key, source_key)
        if link and dedupe_key in seen_links:
            continue
        if link:
            seen_links.add(dedupe_key)

        headlines.append({
            "category": str(news.get("category") or "General").strip(),
            "headline": news.get("ai_headline") or news.get("original_title") or "Untitled",
            "summary": news.get("ai_summary") or "",
            "link": link,
            "source": news.get("source") or "",
            "image_url": _valid_http_url(news.get("image_url")),
            "published_at": news.get("published_at"),
        })

    return headlines


def _limit_email_articles(headlines):
    """Allow up to 10 articles from each RSS source within each category.

    Do not cap the whole category: a category with five RSS feeds can contribute
    up to 50 articles, subject to each feed actually returning that many.
    """
    counts = defaultdict(int)
    limited = []

    for article in headlines:
        category = str(article.get("category") or "General").strip().casefold()
        source = str(article.get("source") or "unknown-source").strip().casefold()
        key = (category, source)
        if counts[key] >= EMAIL_ARTICLES_PER_SOURCE:
            continue
        limited.append(article)
        counts[key] += 1

    print("📊 Email source counts: " + ", ".join(
        f"{category} / {source}: {count}"
        for (category, source), count in sorted(counts.items())
    ))
    return limited


def _send_test_digest():
    """Send one test digest using the test recipient's authorized news only.

    This includes their selected public feeds and all feeds in private categories
    they own. It never includes another user's private cache rows.
    """
    print(f"🧪 TEST MODE ENABLED — destination: {TEST_EMAIL}")

    try:
        users = get_users_with_email()
        test_user = next(
            (u for u in users if (u.get("email") or "").strip().lower() == TEST_EMAIL.strip().lower()),
            None,
        )
        if not test_user:
            print("❌ TEST_EMAIL does not match a Supabase Auth user; cannot safely include private news.")
            return
        raw_news = get_news_from_user_sources(test_user["user_id"])
    except Exception as exc:
        print(f"❌ Could not retrieve authorized test news: {type(exc).__name__}: {exc}")
        return

    headlines = _limit_email_articles(_prepare_email_articles(raw_news))
    if not headlines:
        print("⚠️ Test mode found no cached articles for this user's selected public feeds or owned private categories.")
        return

    category_names = sorted({item.get("category", "General") for item in headlines})
    print(f"📧 Sending TEST digest with {len(headlines)} articles across categories: {', '.join(category_names)}")
    try:
        send_email(to_email=TEST_EMAIL, headlines=headlines)
        print(f"✅ Test email sent to {TEST_EMAIL}")
    except Exception as exc:
        print(f"❌ Test email failed: {type(exc).__name__}: {exc}")


def run_pipeline():
    print("🚀 NEWS PIPELINE: category-visibility-routing-with-test-mode")

    # Collection always runs for both visibility types, including test mode.
    public_stored, public_categories = build_news_cache()
    if public_stored == 0:
        print("⚠️ Public cache was not refreshed; existing cache is preserved where possible.")

    private_stored = collect_private_news()
    print(f"📦 Collection totals: public={public_stored}, private={private_stored}")

    # Test mode sends one digest to the configured test account, including only
    # its selected public news and private categories owned by that same account.
    if TEST_MODE:
        _send_test_digest()
        return

    try:
        users = get_users_with_email()
    except Exception as exc:
        print(f"❌ Could not load users: {type(exc).__name__}: {exc}")
        return

    if not users:
        print("⚠️ No Auth users with email addresses found.")
        return

    sent = failed = skipped = 0
    for user in users:
        user_id = user.get("user_id")
        email = (user.get("email") or "").strip()
        if not user_id or not email:
            continue

        print(f"\n📰 Preparing personalized digest for {email}...")
        try:
            raw_news = get_news_from_user_sources(user_id)
        except Exception as exc:
            print(f"❌ News retrieval failed for {email}: {type(exc).__name__}: {exc}")
            failed += 1
            continue

        headlines = _limit_email_articles(_prepare_email_articles(raw_news))
        if not headlines:
            print(f"⚠️ No cached articles matched selected sources for {email}.")
            skipped += 1
            continue

        try:
            send_email(to_email=email, headlines=headlines)
            sent += 1
            print(f"✅ Digest sent to {email} ({len(headlines)} articles).")
        except Exception as exc:
            failed += 1
            print(f"❌ Email failed for {email}: {type(exc).__name__}: {exc}")

    print(f"\n📬 Delivery complete. Sent: {sent}; failed: {failed}; skipped: {skipped}.")


if __name__ == "__main__":
    run_pipeline()
