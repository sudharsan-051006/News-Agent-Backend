from storage import (
    get_users_with_preferences_and_email,
    insert_news_cache,
    get_cached_news_for_categories,
    clear_news_cache,
    is_cache_present,
)
from agents.news_collector import collect_news
from agents.headline_generator import generate_headline
from agents.email_sender import send_email

ALL_CATEGORIES = ["tech", "sports", "movies", "geopolitics", "local"]

articles = collect_news(ALL_CATEGORIES)


def build_news_cache():
    print("🧹 Clearing old cache...")
    clear_news_cache()

    print("🧠 Building news cache...")
    articles = collect_news(ALL_CATEGORIES)

    for article in articles:
        ai_headline = generate_headline(article)
        insert_news_cache(article, ai_headline)

    print("✅ News cache built")



def run_pipeline():
    users = get_users_with_preferences_and_email()

    if not users:
        print("⚠️ No users with preferences found")
        return

    # 1️⃣ ALWAYS rebuild cache once per run
    build_news_cache()

    # 2️⃣ Send emails
    for user in users:
        print(f"\n📨 Processing user: {user['email']}")

        raw_news = get_cached_news_for_categories(user["categories"])

        if not raw_news:
            print("⚠️ No news for user categories")
            continue

        headlines = [
            {
                "category": n["category"],
                "headline": n["ai_headline"],
                "link": n["link"],
            }
            for n in raw_news
        ]

        send_email(
            to_email=user["email"],
            headlines=headlines
        )

        print("✅ Email sent")

    print("\n📦 Cache retained until next run")


if __name__ == "__main__":
    run_pipeline()
