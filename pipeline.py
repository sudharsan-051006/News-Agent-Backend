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


# Test mode: send at most one email per pipeline run.
TEST_EMAIL = "sudharsanreddy.saragada@gmail.com"


def _has_image(article):
    """Return True when the article contains a non-empty image URL."""
    value = article.get("image_url")
    return isinstance(value, str) and bool(value.strip())


def build_news_cache():
    print("🧹 Clearing old cache...")
    try:
        clear_news_cache()
    except Exception as exc:
        print(f"❌ Failed to clear news cache: {type(exc).__name__}: {exc}")
        return 0

    print("🌐 Fetching RSS sources from DB...")
    try:
        sources = get_all_sources()
    except Exception as exc:
        print(f"❌ Failed to fetch RSS sources: {type(exc).__name__}: {exc}")
        return 0

    if not sources:
        print("⚠️ No RSS sources found in DB.")
        return 0

    # Keep a separate entry when one feed URL is assigned to multiple categories.
    unique_sources_map = {}
    for source in sources:
        url = source.get("rss_url")
        category = source.get("category")
        if url and category:
            unique_sources_map[(url, category)] = {
                "rss_url": url,
                "category": category,
            }

    unique_sources = list(unique_sources_map.values())
    print(f"📡 Fetching from {len(unique_sources)} unique feed/category pairs...")

    try:
        articles = fetch_from_rss_sources(unique_sources)
    except Exception as exc:
        print(f"❌ RSS collection failed: {type(exc).__name__}: {exc}")
        return 0

    if not articles:
        print("⚠️ No articles fetched.")
        return 0

    found_images = sum(1 for article in articles if _has_image(article))
    print(f"🖼️ Collector supplied images for {found_images}/{len(articles)} articles.")

    processed = 0
    stored_images = 0

    for article in articles:
        title = str(article.get("title") or "Untitled")
        image_url = article.get("image_url")

        print(
            f"🔎 PIPELINE IMAGE: {'FOUND' if _has_image(article) else 'NULL'} | "
            f"{title[:90]}"
        )
        if image_url:
            print(f"   Image URL: {image_url}")

        try:
            ai_headline = generate_headline(article)
            ai_summary = generate_ai_summary(article)

            # insert_news_cache should store article['image_url'] in the image_url column.
            insert_news_cache(article, ai_headline, ai_summary)
            processed += 1

            if _has_image(article):
                stored_images += 1

        except Exception as exc:
            print(f"⚠️ Failed processing article {title!r}: {type(exc).__name__}: {exc}")

    print(
        f"✅ News cache built: {processed}/{len(articles)} articles stored; "
        f"{stored_images} stored articles had image URLs before insertion."
    )
    print(
        "ℹ️ The 'stored articles had image URLs' count reflects the URLs passed "
        "to storage; verify the DB INSERT RESULT IMAGE log to confirm persistence."
    )
    return processed


def run_pipeline():
    try:
        users = get_users_with_email()
    except Exception as exc:
        print(f"❌ Failed to fetch users: {type(exc).__name__}: {exc}")
        return

    if not users:
        print("⚠️ No Auth users with email addresses found.")
        return

    stored_count = build_news_cache()
    if stored_count == 0:
        print("⚠️ No articles were stored; skipping email delivery.")
        return

    for user in users:
        print(f"\n📰 Checking selected RSS sources for user: {user.get('email', 'unknown')}")
        try:
            raw_news = get_news_from_user_sources(user["user_id"])
        except Exception as exc:
            print(f"❌ Failed retrieving cached news: {type(exc).__name__}: {exc}")
            continue

        if not raw_news:
            print("⚠️ No cached news matched this user's selected RSS sources.")
            continue

        headlines = []
        for news in raw_news:
            headlines.append(
                {
                    "category": news.get("category") or "General",
                    "headline": (
                        news.get("ai_headline")
                        or news.get("original_title")
                        or "Untitled"
                    ),
                    "summary": news.get("ai_summary") or "",
                    "link": news.get("link") or "",
                    "source": news.get("source") or "",
                    "image_url": news.get("image_url"),
                }
            )

        email_image_count = sum(1 for item in headlines if _has_image(item))
        print(
            f"📧 Preparing {len(headlines)} articles for test email; "
            f"{email_image_count} have image URLs in the payload."
        )

        # Print URLs for diagnosis without logging secrets.
        for item in headlines:
            if _has_image(item):
                print(
                    f"🔗 EMAIL IMAGE URL: {item['image_url']} | "
                    f"{item.get('headline', 'Untitled')[:80]}"
                )

        try:
            send_email(to_email=TEST_EMAIL, headlines=headlines)
            print(f"✅ Test email sent to {TEST_EMAIL}")
        except Exception as exc:
            print(f"❌ Test email failed: {type(exc).__name__}: {exc}")
        return

    print("⚠️ No eligible cached news found for any user's selected RSS sources.")


if __name__ == "__main__":
    run_pipeline()
