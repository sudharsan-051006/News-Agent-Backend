
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
        item.get("title")
        or item.get("original_title")
        or item.get("ai_headline")
        or item.get("headline")
        or "Untitled"
    )[:90]

    image_url = _valid_http_url(item.get("image_url"))
    print(f"🖼️ {stage}: {'FOUND' if image_url else 'NULL/INVALID'} | {title}")

    if image_url:
        print(f"   URL: {image_url}")


def _unique_source_pairs(sources):
    """Deduplicate associations, not categories or owners."""
    result = {}
    for source in sources:
        rss_url = source.get("rss_url")
        category_id = source.get("category_id")
        category = source.get("category") or "General"
        visibility = source.get("visibility")
        owner_id = source.get("owner_id")

        if not rss_url:
            continue

        # Preserve a feed linked to multiple categories and/or owners.
        key = (rss_url, category_id, category, visibility, owner_id)
        result[key] = {
            **source,
            "rss_url": rss_url,
            "category": category,
        }

    return list(result.values())


def _process_articles(articles, label):
    """Generate AI headline/summary while retaining article metadata."""
    processed = []

    for article in articles:
        _log_image(f"{label} COLLECTOR IMAGE", article)

        try:
            headline = generate_headline(article)
            summary = generate_ai_summary(article)
            processed.append((article, headline, summary))
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:80]
            print(
                f"❌ {label} AI processing failed for {title}: "
                f"{type(exc).__name__}: {exc}"
            )

    return processed


def build_news_cache():
    """Collect every RSS association belonging to a public category."""
    print("🌐 Loading public category RSS associations...")

    try:
        sources = _unique_source_pairs(get_all_sources())
    except Exception as exc:
        print(f"❌ Could not load public sources: {type(exc).__name__}: {exc}")
        return 0

    # Defensive visibility check: never route private associations to the
    # shared cache, even if a storage function accidentally returns one.
    sources = [s for s in sources if s.get("visibility") == "public"]

    if not sources:
        print("⚠️ No public RSS associations found; preserving existing cache.")
        return 0

    print(f"📡 Collecting from {len(sources)} public category/feed associations...")

    try:
        articles = fetch_from_rss_sources(sources)
    except Exception as exc:
        print(f"❌ Public collection failed: {type(exc).__name__}: {exc}")
        return 0

    if not articles:
        print("⚠️ No public articles collected; preserving existing cache.")
        return 0

    processed = _process_articles(articles, "PUBLIC")
    if not processed:
        print("⚠️ No public articles processed; preserving existing cache.")
        return 0

    # Do not clear the existing cache until new articles were collected
    # and AI processing completed.
    try:
        clear_news_cache()
    except Exception as exc:
        print(f"❌ Could not clear public cache: {type(exc).__name__}: {exc}")
        return 0

    stored = 0
    for article, headline, summary in processed:
        try:
            insert_news_cache(article, headline, summary)
            stored += 1
        except Exception as exc:
            title = str(article.get("title") or "Untitled")[:80]
            print(
                f"❌ Public cache insert failed for {title}: "
                f"{type(exc).__name__}: {exc}"
            )

    print(f"✅ Public cache stored {stored}/{len(processed)} articles.")
    return stored


def collect_private_news():
    """
    Collect every feed linked to a private category and save its articles
    under that category's owner. Does not consult user_category_sources.
    """
    print("\n🔒 Loading all private category RSS associations...")

    try:
        all_sources = _unique_source_pairs(get_all_private_sources())
    except Exception as exc:
        print(f"❌ Could not load private sources: {type(exc).__name__}: {exc}")
        return 0

    private_sources = [
        source
        for source in all_sources
        if source.get("visibility") == "private" and source.get("owner_id")
    ]

    if not private_sources:
        print("ℹ️ No private category RSS associations found.")
        return 0

    # Collect separately by owner. This keeps private category articles
    # isolated and ensures each feed/category association is preserved.
    sources_by_owner = defaultdict(list)
    for source in private_sources:
        sources_by_owner[str(source["owner_id"])].append(source)

    total_stored = 0

    for owner_id, sources in sources_by_owner.items():
        print(
            f"\n🔒 Owner {owner_id}: collecting "
            f"{len(sources)} private category/feed associations..."
        )

        try:
            articles = fetch_from_rss_sources(sources)
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
        stored_for_owner = 0

        for article, headline, summary in processed:
            try:
                save_private_news_cache(
                    owner_id,
                    article,
                    headline,
                    summary,
                )
                stored_for_owner += 1
            except Exception as exc:
                title = str(article.get("title") or "Untitled")[:80]
                print(
                    f"❌ Private cache save failed for {title}: "
                    f"{type(exc).__name__}: {exc}"
                )

        total_stored += stored_for_owner
        print(
            f"🔒 Owner {owner_id}: saved/updated "
            f"{stored_for_owner}/{len(processed)} private articles."
        )

    print(f"✅ Total private articles saved/updated: {total_stored}")
    return total_stored


def run_pipeline():
    print("🚀 NEWS PIPELINE: category-visibility-routing")

    # Public categories -> news_cache
    public_stored = build_news_cache()
    if public_stored == 0:
        print("⚠️ Public cache was not refreshed; previous cache is preserved.")

    # Private categories -> private_news_cache, grouped by category owner
    private_stored = collect_private_news()
    print(
        f"📦 Collection totals: public={public_stored}, "
        f"private={private_stored}"
    )

    # Email delivery remains personalized using the existing selection logic.
    try:
        users = get_users_with_email()
    except Exception as exc:
        print(f"❌ Could not load users: {type(exc).__name__}: {exc}")
        return

    if not users:
        print("⚠️ No Auth users with email addresses found.")
        return

    emails_sent = 0
    emails_failed = 0

    for user in users:
        user_id = user.get("user_id")
        user_email = (user.get("email") or "").strip()

        if not user_id or not user_email:
            continue

        print(f"\n📰 Preparing digest for {user_email}...")

        try:
            raw_news = get_news_from_user_sources(user_id)
        except Exception as exc:
            print(
                f"❌ News retrieval failed for {user_email}: "
                f"{type(exc).__name__}: {exc}"
            )
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
                "headline": (
                    news.get("ai_headline")
                    or news.get("original_title")
                    or "Untitled"
                ),
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
            print(
                f"❌ Email failed for {user_email}: "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        f"\n📬 Delivery complete. Sent: {emails_sent}; "
        f"failed: {emails_failed}."
    )


if __name__ == "__main__":
    run_pipeline()
