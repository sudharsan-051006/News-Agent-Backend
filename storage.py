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

def get_users_with_preferences_and_email():
    # 1️⃣ Fetch preferences
    prefs = (
        supabase
        .table("preferences")
        .select("user_id, category")
        .execute()
        .data
    )

    if not prefs:
        return []

    # 2️⃣ Group categories per user
    user_categories = defaultdict(list)
    for row in prefs:
        user_categories[row["user_id"]].append(row["category"])

    # 3️⃣ Fetch auth users (ADMIN)
    auth_users = supabase.auth.admin.list_users()

    # 👉 IMPORTANT FIX HERE
    # auth_users is already a LIST
    email_map = {
        user.id: user.email
        for user in auth_users
    }

    # 4️⃣ Build final user list
    users = []
    for user_id, categories in user_categories.items():
        email = email_map.get(user_id)
        if not email:
            continue

        users.append({
            "user_id": user_id,
            "email": email,
            "categories": categories
        })

    return users


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
