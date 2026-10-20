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


def _clean_string_list(values):
    """Return unique, non-empty string values while preserving order."""
    cleaned = []
    seen = set()
    for value in values or []:
        if value is None:
            continue
        value = str(value).strip()
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    return cleaned


def insert_news_cache(article, ai_headline, ai_summary):
    """Insert one deduplicated article with all category/source associations."""
    image_url = article.get("image_url")
    if image_url:
        image_url = str(image_url).strip() or None

    categories = _clean_string_list(
        article.get("categories") or [article.get("category") or "General"]
    )
    sources = _clean_string_list(
        article.get("sources") or [article.get("source")]
    )

    data = {
        # Scalar fields remain for compatibility with existing clients.
        "category": article.get("category") or (categories[0] if categories else "General"),
        "categories": categories,
        "source": article.get("source") or (sources[0] if sources else None),
        "sources": sources,
        "original_title": article.get("title"),
        "ai_headline": ai_headline,
        "ai_summary": ai_summary,
        "link": article.get("link") or article.get("url"),
        "image_url": image_url,
        "published_at": article.get("published_at"),
    }
    print(
        f"💾 DB INSERT IMAGE: {'FOUND' if image_url else 'NULL'} | "
        f"{str(article.get('title') or 'Untitled')[:90]}"
    )
    result = supabase.table("news_cache").insert(data).execute()
    inserted = getattr(result, "data", None) or []
    if inserted:
        saved_image = inserted[0].get("image_url")
        print(f"💾 DB INSERT RESULT IMAGE: {'FOUND' if saved_image else 'NULL'}")
    return result


def get_cached_news_for_categories(categories):
    """Return cached news matching any category, including merged category arrays."""
    categories = _clean_string_list(categories)
    if not categories:
        return []

    # The scalar query supports existing clients; the array query includes
    # deduplicated articles whose requested category is not the representative's.
    scalar_response = (
        supabase.table("news_cache")
        .select("category, categories, ai_headline, ai_summary, link, image_url, source, sources")
        .in_("category", categories)
        .execute()
    )
    array_response = (
        supabase.table("news_cache")
        .select("category, categories, ai_headline, ai_summary, link, image_url, source, sources")
        .overlaps("categories", categories)
        .execute()
    )

    combined = []
    seen = set()
    for row in (scalar_response.data or []) + (array_response.data or []):
        key = row.get("link") or (row.get("ai_headline"), row.get("source"))
        if key not in seen:
            seen.add(key)
            combined.append(row)
    return combined


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
    """Return each cached story once if any of its source feeds is selected by the user."""
    user_sources = (
        supabase.table("user_sources")
        .select("rss_id")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    rss_ids = [row["rss_id"] for row in user_sources if row.get("rss_id") is not None]
    if not rss_ids:
        print(f"⚠️ User {user_id} has no selected RSS sources.")
        return []

    rss_rows = (
        supabase.table("rss")
        .select("id, rss_url, category")
        .in_("id", rss_ids)
        .execute()
        .data
        or []
    )
    selected_sources = _clean_string_list(row.get("rss_url") for row in rss_rows)
    selected_categories = _clean_string_list(row.get("category") for row in rss_rows)
    if not selected_sources:
        print(f"⚠️ No RSS URLs found for user {user_id}.")
        return []

    # PostgREST overlaps uses PostgreSQL array overlap (&&). This returns each
    # news_cache row once even when multiple selected feeds match the sources array.
    response = (
        supabase.table("news_cache")
        .select("category, categories, ai_headline, ai_summary, link, source, sources, image_url")
        .overlaps("sources", selected_sources)
        .execute()
    )
    news = response.data or []

    # Pick a category relevant to this user's selected feeds where possible.
    # Category is presentation metadata only; it never participates in deduplication.
    for item in news:
        item_categories = _clean_string_list(item.get("categories") or [item.get("category")])
        matching_categories = [cat for cat in selected_categories if cat in item_categories]
        if matching_categories:
            item["category"] = matching_categories[0]
        elif not item.get("category") and item_categories:
            item["category"] = item_categories[0]

    image_count = sum(1 for item in news if item.get("image_url"))
    print(
        f"📰 Retrieved {len(news)} unique articles for user {user_id}; "
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
