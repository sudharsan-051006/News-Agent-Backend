from supabase_client import supabase
from collections import defaultdict
from datetime import datetime, timedelta
# from collections import defaultdict

def get_auth_users_map():
    """
    Returns:
      {
        user_id (uuid): email
      }
    """
    users = supabase.auth.admin.list_users()

    return {
        user.user_metadata.get("sub", user.id): user.email
        for user in users.users
    }

def get_all_sources():
    response = supabase.table("user_sources") \
        .select("rss(id, rss_url, category)") \
        .execute()

    data = response.data

    sources = []
    for row in data:
        rss = row.get("rss")
        if rss:
            sources.append({
                "rss_url": rss["rss_url"],
                "category": rss["category"]
            })

    return sources

def insert_news_cache(article, ai_headline, ai_summary):
    """
    article: {
        category, title, link, source?, published_at?
    }
    """

    data = {
        "category": article["category"],
        "source": article.get("source"),
        "original_title": article.get("title"),
        "ai_headline": ai_headline,
        "ai_summary": ai_summary,
        "link": article.get("link"),
        "published_at": article.get("published_at")
    }

    supabase.table("news_cache").insert(data).execute()


def get_cached_news_for_categories(categories):
    """
    categories: ["tech", "sports"]
    returns: list of cached news
    """

    if not categories:
        return []

    response = (
        supabase
        .table("news_cache")
        .select("category, ai_headline, ai_summary, link")
        .in_("category", categories)
        .execute()
    )

    return response.data


def is_cache_present():
    response = (
        supabase
        .table("news_cache")
        .select("id")
        .limit(1)
        .execute()
    )

    return len(response.data) > 0

def clear_news_cache():
    supabase.table("news_cache").delete().is_("id", "not_null").execute()



def clear_old_news_cache(hours=2):
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(hours=hours)

    supabase.table("news_cache") \
        .delete() \
        .lt("created_at", cutoff.isoformat()) \
        .execute()


from collections import defaultdict

def get_users_with_email():
    auth_users = supabase.auth.admin.list_users()

    users = []

    for user in auth_users:
        if not user.email:
            continue

        users.append({
            "user_id": user.id,
            "email": user.email
        })

    return users

def get_news_from_user_sources(user_id):
    # 1️⃣ Get user's selected rss_ids
    user_sources = (
        supabase
        .table("user_sources")
        .select("rss_id")
        .eq("user_id", user_id)
        .execute()
        .data
    )

    if not user_sources:
        return []

    rss_ids = [row["rss_id"] for row in user_sources]

    # 2️⃣ Get rss URLs from rss table
    rss_rows = (
        supabase
        .table("rss")
        .select("id, rss_url")
        .in_("id", rss_ids)
        .execute()
        .data
    )

    if not rss_rows:
        return []

    rss_urls = [r["rss_url"] for r in rss_rows]

    # 3️⃣ Get matching news from cache
    news = (
        supabase
        .table("news_cache")
        .select("category, ai_headline, ai_summary, link, source")
        .in_("source", rss_urls)
        .execute()
        .data
    )

    return news

def was_email_sent_recently(user_id, minutes=60):
    since_time = datetime.utcnow() - timedelta(minutes=minutes)

    response = (
        supabase
        .table("delivery_logs")
        .select("id")
        .eq("user_id", user_id)
        .gte("sent_at", since_time.isoformat())
        .execute()
    )

    return len(response.data) > 0


def log_email_sent(user_id):
    supabase.table("delivery_logs").insert({
        "user_id": user_id
    }).execute()
