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
    """
    Load RSS feeds associated with public categories for universal Trending.

    Use explicit foreign-key names to avoid ambiguous PostgREST relationships.
    Private-category feeds are excluded from the global trending pipeline.
    """
    sources = []
    seen = set()

    def add_source(rss, category_row=None):
        if isinstance(rss, list):
            rss = rss[0] if rss else None

        if isinstance(category_row, list):
            category_row = category_row[0] if category_row else None

        if not rss or not category_row:
            return

        if category_row.get("visibility") != "public":
            return

        rss_url = (rss.get("rss_url") or "").strip()
        category = (
            category_row.get("name")
            or rss.get("category")
            or "General"
        ).strip()

        if not rss_url:
            return

        # A URL can belong to multiple categories. Preserve each association.
        key = (rss_url, category.lower())

        if key not in seen:
            seen.add(key)
            sources.append({
                "rss_url": rss_url,
                "category": category,
            })

    # Current many-to-many category/source associations.
    response = (
        supabase.table("category_sources")
        .select(
            "rss_id,category_id,"
            "rss!category_sources_rss_id_fkey(id,rss_url,category),"
            "categories!category_sources_category_id_fkey(name,visibility)"
        )
        .execute()
    )

    for row in response.data or []:
        add_source(row.get("rss"), row.get("categories"))

    # Backward compatibility for legacy RSS records using category_id.
    legacy = (
        supabase.table("rss")
        .select(
            "id,rss_url,category,category_id,"
            "categories!rss_category_id_fkey(name,visibility)"
        )
        .not_.is_("category_id", "null")
        .execute()
    )

    for row in legacy.data or []:
        add_source(row, row.get("categories"))

    print(
        f"📰 Loaded {len(sources)} RSS/category associations "
        "for universal Trending."
    )

    return sources


def insert_news_cache(article, ai_headline, ai_summary):
    """Insert processed news and preserve its extracted image URL."""
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

    result = (
        supabase.table("news_cache")
        .insert(data)
        .execute()
    )

    inserted = getattr(result, "data", None) or []

    if inserted:
        saved_image = inserted[0].get("image_url")
        print(
            f"💾 DB INSERT RESULT IMAGE: "
            f"{'FOUND' if saved_image else 'NULL'}"
        )

    return result


def get_cached_news_for_categories(categories):
    """Return cached articles for the requested categories."""
    if not categories:
        return []

    response = (
        supabase.table("news_cache")
        .select(
            "category,ai_headline,ai_summary,link,"
            "image_url,source"
        )
        .in_("category", categories)
        .execute()
    )

    return response.data or []


def is_cache_present():
    """Return whether the news cache contains at least one record."""
    response = (
        supabase.table("news_cache")
        .select("id")
        .limit(1)
        .execute()
    )

    return bool(response.data)


def clear_news_cache():
    """Delete all cached news records."""
    (
        supabase.table("news_cache")
        .delete()
        .not_.is_("id", "null")
        .execute()
    )


def clear_old_news_cache(hours=2):
    """Delete cached news older than the specified number of hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    (
        supabase.table("news_cache")
        .delete()
        .lt("created_at", cutoff.isoformat())
        .execute()
    )


def get_users_with_email():
    """Return Supabase Auth users with email addresses."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)

    return [
        {"user_id": user.id, "email": user.email}
        for user in auth_users
        if getattr(user, "email", None)
    ]


def get_news_from_user_sources(user_id):
    """
    Fetch cached news from the authenticated user's selected sources.

    Public categories can be followed. Private categories are accessible
    only to their owners.
    """
    user_sources = (
        supabase.table("user_category_sources")
        .select(
            "rss_id,category_id,"
            "categories!user_category_sources_category_id_fkey("
            "name,visibility,owner_id)"
        )
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )

    rss_ids = []

    for row in user_sources:
        rss_id = row.get("rss_id")

        if rss_id is None:
            continue

        category_row = row.get("categories")

        if isinstance(category_row, list):
            category_row = category_row[0] if category_row else None

        if not category_row:
            continue

        visibility = category_row.get("visibility")
        owner_id = category_row.get("owner_id")

        if visibility == "private" and owner_id != user_id:
            continue

        if visibility not in ("public", "private"):
            continue

        rss_ids.append(rss_id)

    rss_ids = list(set(rss_ids))

    if not rss_ids:
        print(
            f"⚠️ User {user_id} has no accessible selected RSS sources."
        )
        return []

    rss_rows = (
        supabase.table("rss")
        .select("id,rss_url")
        .in_("id", rss_ids)
        .execute()
        .data
        or []
    )

    rss_urls = list({
        row["rss_url"]
        for row in rss_rows
        if row.get("rss_url")
    })

    if not rss_urls:
        print(f"⚠️ No RSS URLs found for user {user_id}.")
        return []

    response = (
        supabase.table("news_cache")
        .select(
            "category,ai_headline,ai_summary,link,"
            "source,image_url"
        )
        .in_("source", rss_urls)
        .execute()
    )

    news = response.data or []
    image_count = sum(
        1 for item in news if item.get("image_url")
    )

    print(
        f"📰 Retrieved {len(news)} articles for user {user_id}; "
        f"{image_count} have image URLs."
    )

    return news


def was_email_sent_recently(user_id, minutes=60):
    """Check whether an email was sent to the user recently."""
    since_time = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    )

    response = (
        supabase.table("delivery_logs")
        .select("id")
        .eq("user_id", user_id)
        .gte("sent_at", since_time.isoformat())
        .execute()
    )

    return bool(response.data)


def log_email_sent(user_id):
    """Record a successful email delivery."""
    return (
        supabase.table("delivery_logs")
        .insert({"user_id": user_id})
        .execute()
    )
