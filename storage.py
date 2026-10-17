
from supabase_client import supabase
from datetime import datetime, timedelta


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
    response = (
        supabase.table("user_sources")
        .select("rss(id, rss_url, category)")
        .execute()
    )

    sources = []

    for row in response.data:
        rss = row.get("rss")

        if rss:
            sources.append({
                "rss_url": rss["rss_url"],
                "category": rss["category"],
            })

    return sources


def insert_news_cache(article, ai_headline, ai_summary):
    """
    Store a processed article, including its image URL.

    Expected article fields:
        category, title, link, source, image_url
    """

    data = {
        "category": article["category"],
        "source": article.get("source"),
        "original_title": article.get("title"),
        "ai_headline": ai_headline,
        "ai_summary": ai_summary,
        "link": article.get("link"),
        "image_url": article.get("image_url"),
        "published_at": article.get("published_at"),
    }

    supabase.table("news_cache").insert(data).execute()


def get_cached_news_for_categories(categories):
    """
    Args:
        categories: e.g. ["tech", "sports"]

    Returns:
        Cached news including image URLs.
    """
    if not categories:
        return []

    response = (
        supabase.table("news_cache")
        .select(
            "category, ai_headline, ai_summary, "
            "link, image_url, source"
        )
        .in_("category", categories)
        .execute()
    )

    return response.data


def is_cache_present():
    response = (
        supabase.table("news_cache")
        .select("id")
        .limit(1)
        .execute()
    )

    return len(response.data) > 0


def clear_news_cache():
    supabase.table("news_cache").delete().is_("id", "not_null").execute()


def clear_old_news_cache(hours=2):
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    (
        supabase.table("news_cache")
        .delete()
        .lt("created_at", cutoff.isoformat())
        .execute()
    )


def get_users_with_email():
    auth_users = supabase.auth.admin.list_users()

    users = []

    for user in auth_users:
        if not user.email:
            continue

        users.append({
            "user_id": user.id,
            "email": user.email,
        })

    return users


def get_news_from_user_sources(user_id):
    """
    Fetch cached news from the RSS sources selected by a user.
    Includes image_url for rendering in the email digest.
    """

    # 1. Get the user's selected RSS IDs.
    user_sources = (
        supabase.table("user_sources")
        .select("rss_id")
        .eq("user_id", user_id)
        .execute()
        .data
    )

    if not user_sources:
        return []

    rss_ids = [
        row["rss_id"]
        for row in user_sources
        if row.get("rss_id") is not None
    ]

    if not rss_ids:
        return []

    # 2. Get the corresponding RSS URLs.
    rss_rows = (
        supabase.table("rss")
        .select("id, rss_url")
        .in_("id", rss_ids)
        .execute()
        .data
    )

    if not rss_rows:
        return []

    rss_urls = [
        row["rss_url"]
        for row in rss_rows
        if row.get("rss_url")
    ]

    if not rss_urls:
        return []

    # 3. Fetch cached news and its image URL.
    response = (
        supabase.table("news_cache")
        .select(
            "category, ai_headline, ai_summary, "
            "link, source, image_url"
        )
        .in_("source", rss_urls)
        .execute()
    )

    news = response.data or []

    print(
        f"📰 Retrieved {len(news)} articles for user "
        f"{user_id}; "
        f"{sum(1 for item in news if item.get('image_url'))} "
        "have image URLs."
    )

    return news


def was_email_sent_recently(user_id, minutes=60):
    since_time = datetime.utcnow() - timedelta(minutes=minutes)

    response = (
        supabase.table("delivery_logs")
        .select("id")
        .eq("user_id", user_id)
        .gte("sent_at", since_time.isoformat())
        .execute()
    )

    return len(response.data) > 0


def log_email_sent(user_id):
    supabase.table("delivery_logs").insert({
        "user_id": user_id,
    }).execute()
