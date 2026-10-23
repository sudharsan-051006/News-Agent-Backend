"""Supabase storage helpers for Elinity's category-based news pipeline."""
from datetime import datetime, timedelta, timezone

from supabase_client import supabase

PUBLIC_CATEGORIES = {"tech",  "sports", "movies", "geopolitics", "local"}


def _rows(table, columns="*"):
    response = supabase.table(table).select(columns).execute()
    return response.data or []


def _norm(value):
    return str(value or "").strip().lower()


def get_auth_users_map():
    """Return {user_id: email} for Supabase Auth users."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)
    return {
        user.user_metadata.get("sub", user.id): user.email
        for user in auth_users
        if getattr(user, "email", None)
    }


def get_users_with_email():
    """Return Auth users that have email addresses."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)
    return [
        {"user_id": user.id, "email": user.email}
        for user in auth_users
        if getattr(user, "email", None)
    ]


def get_all_sources():
    """Return every RSS feed mapped to a public category, once per category.

    This intentionally uses category_sources + categories + rss rather than
    user_sources. A user's selection must not restrict the shared public cache
    to a single RSS feed.
    """
    categories = _rows("categories", "id, name, visibility")
    public_by_id = {}
    for category in categories:
        name = (category.get("name") or "").strip()
        visibility = _norm(category.get("visibility"))
        if name and visibility == "public":
            public_by_id[str(category.get("id"))] = name

    if not public_by_id:
        print("⚠️ No categories with visibility='public' found.")
        return []

    mappings = _rows("category_sources", "category_id, rss_id")
    rss_rows = _rows("rss", "id, name, rss_url")
    rss_by_id = {str(row.get("id")): row for row in rss_rows if row.get("id") is not None}

    sources, seen = [], set()
    for mapping in mappings:
        category_name = public_by_id.get(str(mapping.get("category_id")))
        rss = rss_by_id.get(str(mapping.get("rss_id")))
        if not category_name or not rss:
            continue
        url = (rss.get("rss_url") or "").strip()
        if not url:
            continue
        key = (url, _norm(category_name))
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "rss_url": url,
            "category": _norm(category_name),
            "name": rss.get("name") or url,
        })

    print(f"📰 Loaded {len(sources)} public RSS/category associations from Supabase.")
    counts = {}
    for source in sources:
        counts[source["category"]] = counts.get(source["category"], 0) + 1
    for category, count in sorted(counts.items()):
        print(f"   • {category}: {count} feed(s)")
    return sources


def get_public_categories():
    """Return normalized names of all public categories."""
    result = []
    for row in _rows("categories", "name, visibility"):
        name = _norm(row.get("name"))
        if name and _norm(row.get("visibility")) == "public":
            result.append(name)
    return sorted(set(result))


def get_user_selected_categories(user_id):
    """Get topic/category choices for a user from user_category_sources.

    Returns [] if no category preferences exist, allowing the caller to avoid
    silently sending unrelated news.
    """
    try:
        choices = (
            supabase.table("user_category_sources")
            .select("category_id")
            .eq("user_id", user_id)
            .execute().data or []
        )
    except Exception as exc:
        print(f"⚠️ Could not read user_category_sources: {type(exc).__name__}: {exc}")
        choices = []

    category_ids = list({str(row.get("category_id")) for row in choices if row.get("category_id") is not None})
    if category_ids:
        rows = (
            supabase.table("categories")
            .select("id, name, visibility")
            .in_("id", category_ids)
            .execute().data or []
        )
        selected = sorted({
            _norm(row.get("name")) for row in rows
            if row.get("name") and _norm(row.get("visibility")) == "public"
        })
        if selected:
            print(f"🎯 Selected public topics for {user_id}: {', '.join(selected)}")
            return selected

    # Backward compatibility for installations where users select individual
    # feeds in user_sources and the legacy rss.category column still exists.
    try:
        rows = (
            supabase.table("user_sources")
            .select("rss_id")
            .eq("user_id", user_id)
            .execute().data or []
        )
        rss_ids = list({str(row.get("rss_id")) for row in rows if row.get("rss_id") is not None})
        if rss_ids:
            rss_rows = (
                supabase.table("rss")
                .select("id, category")
                .in_("id", rss_ids)
                .execute().data or []
            )
            selected = sorted({_norm(row.get("category")) for row in rss_rows if row.get("category")})
            if selected:
                print(f"🎯 Legacy selected topics for {user_id}: {', '.join(selected)}")
                return selected
    except Exception as exc:
        print(f"⚠️ Legacy user source lookup failed: {type(exc).__name__}: {exc}")

    return []


def insert_news_cache(article, ai_headline, ai_summary):
    """Insert processed article data, preserving the collector's image_url."""
    image_url = str(article.get("image_url") or "").strip() or None
    data = {
        "category": _norm(article.get("category")) or "general",
        "source": article.get("source"),
        "original_title": article.get("title"),
        "ai_headline": ai_headline,
        "ai_summary": ai_summary,
        "link": article.get("link"),
        "image_url": image_url,
        "published_at": article.get("published_at"),
    }
    print(f"💾 DB INSERT IMAGE: {'FOUND' if image_url else 'NULL'} | {article.get('title', 'Untitled')[:90]}")
    result = supabase.table("news_cache").insert(data).execute()
    inserted = getattr(result, "data", None) or []
    if inserted:
        print(f"💾 DB INSERT RESULT IMAGE: {'FOUND' if inserted[0].get('image_url') else 'NULL'}")
    return result


def get_cached_news_for_categories(categories):
    """Return cached news for all requested categories, including images."""
    normalized = sorted({_norm(category) for category in (categories or []) if _norm(category)})
    if not normalized:
        return []
    response = (
        supabase.table("news_cache")
        .select("category, ai_headline, original_title, ai_summary, link, image_url, source, published_at")
        .in_("category", normalized)
        .execute()
    )
    return response.data or []


def get_news_from_user_sources(user_id):
    """Compatibility helper: retrieve cached articles for selected RSS URLs."""
    user_sources = (
        supabase.table("user_sources").select("rss_id").eq("user_id", user_id).execute().data or []
    )
    rss_ids = list({str(row["rss_id"]) for row in user_sources if row.get("rss_id") is not None})
    if not rss_ids:
        return []
    rss_rows = supabase.table("rss").select("id, rss_url").in_("id", rss_ids).execute().data or []
    urls = list({row["rss_url"] for row in rss_rows if row.get("rss_url")})
    if not urls:
        return []
    return supabase.table("news_cache").select(
        "category, ai_headline, original_title, ai_summary, link, source, image_url, published_at"
    ).in_("source", urls).execute().data or []


def is_cache_present():
    response = supabase.table("news_cache").select("id").limit(1).execute()
    return bool(response.data)


def clear_news_cache():
    supabase.table("news_cache").delete().not_.is_("id", "null").execute()


def clear_old_news_cache(hours=2):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    supabase.table("news_cache").delete().lt("created_at", cutoff.isoformat()).execute()


def was_email_sent_recently(user_id, minutes=60):
    since_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    response = (
        supabase.table("delivery_logs").select("id").eq("user_id", user_id)
        .gte("sent_at", since_time.isoformat()).execute()
    )
    return bool(response.data)


def log_email_sent(user_id):
    return supabase.table("delivery_logs").insert({"user_id": user_id}).execute()
