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


# Test mode: the pipeline sends at most one test email to this address.
TEST_EMAIL = "sudharsanreddy.saragada@gmail.com"


def build_news_cache():
    print("🧹 Clearing old cache...")
    clear_news_cache()

    print("🌐 Fetching RSS sources from DB...")
    sources = get_all_sources()
    if not sources:
        print("⚠️ No RSS sources found in DB.")
        return 0

    # Preserve a feed URL associated with multiple categories.
    unique_sources_map = {}
    for source in sources:
        url, category = source.get("rss_url"), source.get("category")
        if url and category:
            unique_sources_map[(url, category)] = {
                "rss_url": url,
                "category": category,
            }
    unique_sources = list(unique_sources_map.values())
    print(f"📡 Fetching from {len(unique_sources)} unique feed/category pairs...")

    articles = fetch_from_rss_sources(unique_sources)
    if not articles:
        print("⚠️ No articles fetched.")
        return 0

    print(f"🧠 Processing {len(articles)} articles with AI...")
    found_images = sum(1 for article in articles if article.get("image_url"))
    print(f"🖼️ Collector supplied images for {found_images}/{len(articles)} articles.")

    processed = 0
    for article in articles:
        try:
            image_url = article.get("image_url")
            print(
                f"🔎 PIPELINE IMAGE: {'FOUND' if image_url else 'NULL'} | "
                f"{article.get('title', 'Untitled')[:90]}"
            )
            ai_headline = generate_headline(article)
            ai_summary = generate_ai_summary(article)
            insert_news_cache(article, ai_headline, ai_summary)
            processed += 1
        except Exception as exc:
            print(
                f"⚠️ Failed processing article "
                f"{article.get('title', 'Untitled')!r}: {exc}"
            )

    print(f"✅ News cache built: {processed}/{len(articles)} articles stored.")
    return processed


def run_pipeline():
    users = get_users_with_email()
    if not users:
        print("⚠️ No Auth users with email addresses found.")
        return

    build_news_cache()

    for user in users:
        print(f"\n📰 Checking selected RSS sources for user: {user['email']}")
        try:
            raw_news = get_news_from_user_sources(user["user_id"])
            if not raw_news:
                print("⚠️ No cached news matched this user's selected RSS sources.")
                continue

            headlines = []
            for news in raw_news:
                headlines.append({
                    "category": news.get("category", "General"),
                    "headline": (
                        news.get("ai_headline")
                        or news.get("original_title")
                        or "Untitled"
                    ),
                    "summary": news.get("ai_summary") or "",
                    "link": news.get("link") or "",
                    "source": news.get("source") or "",
                    # Critical: carry the stored URL into the email renderer.
                    "image_url": news.get("image_url"),
                })

            email_image_count = sum(
                1 for item in headlines if item.get("image_url")
            )
            print(
                f"📧 Preparing {len(headlines)} articles for test email; "
                f"{email_image_count} have image URLs in the payload."
            )
            send_email(to_email=TEST_EMAIL, headlines=headlines)
            print(f"✅ Test email sent to {TEST_EMAIL}")
            return
        except Exception as exc:
            print(f"❌ Test email failed: {type(exc).__name__}: {exc}")
            return

    print("⚠️ No eligible cached news found for any user's selected RSS sources.")


if __name__ == "__main__":
    run_pipeline()
