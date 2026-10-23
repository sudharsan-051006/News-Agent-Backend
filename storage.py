from datetime import datetime, timedelta, timezone

from supabase_client import supabase


# Cache columns deliberately include original_title because the digest pipeline
# uses it as a fallback when AI headline generation is unavailable.
CACHE_COLUMNS = (
    "category, original_title, ai_headline, ai_summary, link, "
    "image_url, source, published_at"
)


def _rows(response):
    return getattr(response, "data", None) or []


def get_users_with_email():
    """Return Supabase Auth users that have email addresses."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)
    users = []
    for user in auth_users:
        email = getattr(user, "email", None)
        user_id = getattr(user, "id", None)
        if email and user_id:
            users.append({"user_id": user_id, "email": email})
    return users


def get_all_sources():
    """Return public RSS/category associations for the shared cache only."""
    response = (
        supabase.table("category_sources")
        .select(
            "rss_id, category_id, "
            "rss!category_sources_rss_id_fkey(id, rss_url, category), "
            "categories!category_sources_category_id_fkey(id, name, visibility, owner_id)"
        )
        .execute()
    )

    sources, seen = [], set()
    for row in _rows(response):
        category_info = row.get("categories") or {}
        rss = row.get("rss") or {}
        if category_info.get("visibility") != "public":
            continue

        rss_url = rss.get("rss_url")
        category = category_info.get("name")
        if not rss_url or not category:
            continue

        key = (row.get("rss_id"), row.get("category_id"))
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "rss_id": row.get("rss_id"),
            "category_id": row.get("category_id"),
            "rss_url": rss_url,
            "category": category,
            "visibility": "public",
        })

    print(f"📰 Loaded {len(sources)} public RSS/category associations.")
    return sources


def get_user_selected_sources(user_id):
    """Return only the category/RSS pairs explicitly selected by this user."""
    selections = _rows(
        supabase.table("user_category_sources")
        .select("user_id, category_id, rss_id")
        .eq("user_id", user_id)
        .execute()
    )
    if not selections:
        return []

    category_ids = list({r["category_id"] for r in selections if r.get("category_id")})
    rss_ids = list({r["rss_id"] for r in selections if r.get("rss_id")})
    if not category_ids or not rss_ids:
        return []

    category_rows = _rows(
        supabase.table("categories")
        .select("id, name, visibility, owner_id")
        .in_("id", category_ids)
        .execute()
    )
    categories = {r["id"]: r for r in category_rows if r.get("id")}

    rss_rows = _rows(
        supabase.table("rss")
        .select("id, rss_url, category")
        .in_("id", rss_ids)
        .execute()
    )
    feeds = {r["id"]: r for r in rss_rows if r.get("id")}

    sources, seen = [], set()
    for selection in selections:
        category_info = categories.get(selection.get("category_id"))
        feed = feeds.get(selection.get("rss_id"))
        if not category_info or not feed:
            continue

        visibility = category_info.get("visibility")
        owner_id = category_info.get("owner_id")
        # Public categories are selectable by any user. Private categories are
        # only usable by their owner, even if a stale selection row remains.
        if visibility == "private" and owner_id != user_id:
            continue
        if visibility not in ("public", "private"):
            continue

        rss_url = feed.get("rss_url")
        category_name = category_info.get("name") or feed.get("category") or "General"
        if not rss_url:
            continue

        key = (selection.get("rss_id"), selection.get("category_id"), visibility)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "rss_id": selection.get("rss_id"),
            "category_id": selection.get("category_id"),
            "rss_url": rss_url,
            "category": category_name,
            "visibility": visibility,
            "owner_id": owner_id,
        })
    return sources


def get_user_private_sources(user_id):
    """Return private feeds owned by this user and explicitly selected by them."""
    return [s for s in get_user_selected_sources(user_id) if s.get("visibility") == "private"]


def insert_news_cache(article, ai_headline, ai_summary):
    """Insert one public article/category association into the shared cache."""
    image_url = str(article.get("image_url") or "").strip() or None
    data = {
        "category": article.get("category") or "General",
        "source": article.get("source"),
        "original_title": article.get("title") or article.get("original_title") or "Untitled",
        "ai_headline": ai_headline or article.get("title") or "Untitled",
        "ai_summary": ai_summary or "",
        "link": article.get("link"),
        "image_url": image_url,
        "published_at": article.get("published_at"),
        "categories": article.get("categories") or [article.get("category") or "General"],
        "sources": article.get("sources") or ([article.get("source")] if article.get("source") else []),
    }
    result = supabase.table("news_cache").insert(data).execute()
    print(f"💾 Public article saved: {data['original_title'][:80]} | image={'yes' if image_url else 'no'}")
    return result


def save_private_news_cache(owner_id, article, ai_headline, ai_summary):
    """Insert or update a private article without exposing it in the shared cache.

    private_news_cache in the supplied schema has no category_id/rss_id columns,
    so this stores the category label and RSS URL using its existing columns.
    """
    link = article.get("link")
    if not owner_id or not link:
        raise ValueError("owner_id and article link are required for private cache storage")

    image_url = str(article.get("image_url") or "").strip() or None
    data = {
        "owner_id": owner_id,
        "category": article.get("category") or "General",
        "original_title": article.get("title") or article.get("original_title") or "Untitled",
        "ai_headline": ai_headline or article.get("title") or "Untitled",
        "ai_summary": ai_summary or "",
        "link": link,
        "source": article.get("source"),
        "image_url": image_url,
        "published_at": article.get("published_at"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Avoid requiring an upsert constraint that may not exist in the current DB.
    existing = _rows(
        supabase.table("private_news_cache")
        .select("id")
        .eq("owner_id", owner_id)
        .eq("link", link)
        .limit(1)
        .execute()
    )
    if existing:
        return (
            supabase.table("private_news_cache")
            .update(data)
            .eq("id", existing[0]["id"])
            .eq("owner_id", owner_id)
            .execute()
        )
    return supabase.table("private_news_cache").insert(data).execute()


def get_news_from_user_sources(user_id):
    """Retrieve selected public and private articles, enforcing owner scope."""
    selected = get_user_selected_sources(user_id)
    if not selected:
        print(f"⚠️ User {user_id} has no selected RSS/category associations.")
        return []

    news, seen = [], set()
    for source in selected:
        rss_url = source["rss_url"]
        category = source["category"]
        if source["visibility"] == "public":
            rows = _rows(
                supabase.table("news_cache")
                .select(CACHE_COLUMNS)
                .eq("source", rss_url)
                .eq("category", category)
                .execute()
            )
        else:
            rows = _rows(
                supabase.table("private_news_cache")
                .select(CACHE_COLUMNS)
                .eq("owner_id", user_id)
                .eq("source", rss_url)
                .eq("category", category)
                .execute()
            )

        for row in rows:
            key = (row.get("link"), row.get("category"), source["visibility"])
            if key in seen:
                continue
            seen.add(key)
            # Include IDs/visibility for diagnostics and downstream personalization.
            row["rss_id"] = source.get("rss_id")
            row["category_id"] = source.get("category_id")
            row["visibility"] = source["visibility"]
            news.append(row)

    print(f"📰 Retrieved {len(news)} authorized articles for user {user_id}.")
    return news


def get_cached_news_for_categories(categories):
    if not categories:
        return []
    response = (
        supabase.table("news_cache")
        .select(CACHE_COLUMNS)
        .in_("category", categories)
        .execute()
    )
    return _rows(response)


def is_cache_present():
    return bool(_rows(supabase.table("news_cache").select("id").limit(1).execute()))


def clear_news_cache():
    """Clear shared cache; call only after a successful fresh collection."""
    supabase.table("news_cache").delete().not_.is_("id", "null").execute()


def clear_old_news_cache(hours=2):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    supabase.table("news_cache").delete().lt("created_at", cutoff.isoformat()).execute()


def was_email_sent_recently(user_id, minutes=60):
    since_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    response = (
        supabase.table("delivery_logs")
        .select("id")
        .eq("user_id", user_id)
        .gte("sent_at", since_time.isoformat())
        .execute()
    )
    return bool(_rows(response))


def log_email_sent(user_id):
    return supabase.table("delivery_logs").insert({"user_id": user_id}).execute()
