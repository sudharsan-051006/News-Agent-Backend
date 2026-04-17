from storage import (
    get_users_with_preferences_and_email,
    insert_news_cache,
    get_cached_news_for_categories,
    clear_news_cache,
    get_all_sources,   # ✅ NEW
)

from agents.news_collector import fetch_from_rss_sources  # ✅ UPDATED
from agents.headline_generator import generate_headline, generate_ai_summary
from agents.email_sender import send_email


def build_news_cache():
    print("🧹 Clearing old cache...")
    clear_news_cache()

    print("🌐 Fetching RSS sources from DB...")
    sources = get_all_sources()

    if not sources:
        print("⚠️ No RSS sources found in DB")
        return

    # -----------------------------------
    # ✅ Deduplicate RSS URLs
    # -----------------------------------
    unique_sources_map = {}
    for s in sources:
        url = s["rss_url"]
        category = s["category"]

        # Keep first category (or you can improve this later)
        if url not in unique_sources_map:
            unique_sources_map[url] = category

    unique_sources = [
        {"rss_url": url, "category": cat}
        for url, cat in unique_sources_map.items()
    ]

    print(f"📡 Fetching from {len(unique_sources)} unique sources...")

    # -----------------------------------
    # 📰 Fetch news
    # -----------------------------------
    articles = fetch_from_rss_sources(unique_sources)

    if not articles:
        print("⚠️ No articles fetched")
        return

    print(f"🧠 Processing {len(articles)} articles with AI...")

    # -----------------------------------
    # 🤖 AI processing + store
    # -----------------------------------
    for article in articles:
        try:
            ai_headline = generate_headline(article)
            ai_summary = generate_ai_summary(article)

            insert_news_cache(article, ai_headline, ai_summary)

        except Exception as e:
            print(f"⚠️ Failed processing article: {e}")
            continue

    print("✅ News cache built")


def run_pipeline():
    users = get_users_with_preferences_and_email()

    if not users:
        print("⚠️ No users with preferences found")
        return

    # -----------------------------------
    # 1️⃣ Build cache once
    # -----------------------------------
    build_news_cache()

    # -----------------------------------
    # 2️⃣ Send emails
    # -----------------------------------
    for user in users:
        print(f"\n📨 Processing user: {user['email']}")

        try:
            raw_news = get_cached_news_for_categories(user["categories"])

            if not raw_news:
                print("⚠️ No news for user categories")
                continue

            headlines = [
                {
                    "category": n["category"],
                    "headline": n["ai_headline"],
                    "summary": n.get("ai_summary", ""),
                    "link": n["link"],
                }
                for n in raw_news
            ]

            send_email(
                to_email=user["email"],
                headlines=headlines
            )

            print("✅ Email sent")

        except Exception as e:
            print(f"⚠️ Failed for user {user['email']}: {e}")
            continue

    print("\n📦 Cache retained until next run")


if __name__ == "__main__":
    run_pipeline()
