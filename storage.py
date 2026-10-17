from datetime import datetime, timedelta, timezone

from supabase_client import supabase


def get_auth_users_map():
    """Return {user_id: email} for Supabase Auth users."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)
    return {
        user.user_metadata.get("sub", user.id): user.email
        for user in auth_users
        if getattr(user, "email", None)
    }


def get_all_sources():
    """Return RSS feeds linked to users, preserving URL/category pairs."""
    response = (
        supabase.table("user_sources")
        .select("rss(id, rss_url, category)")
        .execute()
    )
    sources = []
    seen = set()
    for row in response.data or []:
        rss = row.get("rss")
        if not rss:
            continue
        rss_url, category = rss.get("rss_url"), rss.get("category")
        if not rss_url or not category:
            continue
        key = (rss_url, category)
        if key not in seen:
            seen.add(key)
            sources.append({"rss_url": rss_url, "category": category})
    return sources


def insert_news_cache(article, ai_headline, ai_summary):
    """Insert processed article data, preserving the collector's image_url."""
    image_url = article.get("image_url")
    if image_url:
        image_url = str(image_url).strip() or None

    data = {
        "category": article["category"],
        "source": article.get("source"),
        "original_title": article.get("title"),
        "ai_headline": ai_headline,
        "ai_summary": ai_summary,
        "link": article.get("link"),
        "image_url": image_url,
        "published_at": article.get("published_at"),
    }
    print(
        f"💾 DB INSERT IMAGE: {'FOUND' if image_url else 'NULL'} | "
        f"{article.get('title', 'Untitled')[:90]}"
    )
    result = supabase.table("news_cache").insert(data).execute()
    inserted = getattr(result, "data", None) or []
    if inserted:
        saved_image = inserted[0].get("image_url")
        print(f"💾 DB INSERT RESULT IMAGE: {'FOUND' if saved_image else 'NULL'}")
    return result


def get_cached_news_for_categories(categories):
    """Return cached news for categories, including image URLs."""
    if not categories:
        return []
    response = (
        supabase.table("news_cache")
        .select("category, ai_headline, ai_summary, link, image_url, source")
        .in_("category", categories)
        .execute()
    )
    return response.data or []


def is_cache_present():
    response = supabase.table("news_cache").select("id").limit(1).execute()
    return bool(response.data)


def clear_news_cache():
    supabase.table("news_cache").delete().not_.is_("id", "null").execute()


def clear_old_news_cache(hours=2):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    (
        supabase.table("news_cache")
        .delete()
        .lt("created_at", cutoff.isoformat())
        .execute()
    )


def get_users_with_email():
    """Return Auth users that have email addresses."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)
    return [
        {"user_id": user.id, "email": user.email}
        for user in auth_users
        if getattr(user, "email", None)
    ]


def get_news_from_user_sources(user_id):
    """Fetch cached news for the user's selected RSS sources, including images."""
    user_sources = (
        supabase.table("user_sources")
        .select("rss_id")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    rss_ids = [
        row["rss_id"] for row in user_sources if row.get("rss_id") is not None
    ]
    if not rss_ids:
        print(f"⚠️ User {user_id} has no selected RSS sources.")
        return []

    rss_rows = (
        supabase.table("rss")
        .select("id, rss_url")
        .in_("id", rss_ids)
        .execute()
        .data
        or []
    )
    rss_urls = list({row["rss_url"] for row in rss_rows if row.get("rss_url")})
    if not rss_urls:
        print(f"⚠️ No RSS URLs found for user {user_id}.")
        return []

    response = (
        supabase.table("news_cache")
        .select("category, ai_headline, ai_summary, link, source, image_url")
        .in_("source", rss_urls)
        .execute()
    )
    news = response.data or []
    image_count = sum(1 for item in news if item.get("image_url"))
    print(
        f"📰 Retrieved {len(news)} articles for user {user_id}; "
        f"{image_count} have image URLs."
    )
    return news


def was_email_sent_recently(user_id, minutes=60):
    since_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    response = (
        supabase.table("delivery_logs")
        .select("id")
        .eq("user_id", user_id)
        .gte("sent_at", since_time.isoformat())
        .execute()
    )
    return bool(response.data)


def log_email_sent(user_id):
    return supabase.table("delivery_logs").insert({"user_id": user_id}).execute()
