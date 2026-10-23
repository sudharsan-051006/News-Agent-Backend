from datetime import datetime, timedelta, timezone

from supabase_client import supabase

ARTICLES_PER_RSS = 5
ARTICLE_COLUMNS = (
    "category,ai_headline,ai_summary,link,image_url,source,published_at"
)


def _relation_one(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value if isinstance(value, dict) else None


def _published_datetime(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def get_auth_users_map():
    """Return {user_id: email} for Supabase Auth users."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)
    result = {}
    for user in auth_users:
        email = getattr(user, "email", None)
        if not email:
            continue
        metadata = getattr(user, "user_metadata", None) or {}
        result[metadata.get("sub", user.id)] = email
    return result


def get_users_with_email():
    """Return Supabase Auth users with email addresses."""
    response = supabase.auth.admin.list_users()
    auth_users = getattr(response, "users", response)
    return [
        {"user_id": user.id, "email": user.email}
        for user in auth_users
        if getattr(user, "email", None)
    ]


def get_all_sources():
    """Return feeds associated with public categories for shared cache."""
    response = (
        supabase.table("category_sources")
        .select(
            "rss_id,category_id,"
            "rss!category_sources_rss_id_fkey(id,rss_url,category),"
            "categories!category_sources_category_id_fkey(name,visibility)"
        )
        .execute()
    )

    sources, seen = [], set()
    for row in response.data or []:
        rss = _relation_one(row.get("rss"))
        category = _relation_one(row.get("categories"))
        if not rss or not category or category.get("visibility") != "public":
            continue

        rss_url = (rss.get("rss_url") or "").strip()
        category_name = (
            category.get("name") or rss.get("category") or "General"
        ).strip()
        key = (rss_url, category_name.casefold())
        if rss_url and key not in seen:
            seen.add(key)
            sources.append({
                "rss_id": rss.get("id") or row.get("rss_id"),
                "rss_url": rss_url,
                "category": category_name,
            })

    # Legacy RSS records may still use rss.category_id instead of the join table.
    try:
        legacy_response = (
            supabase.table("rss")
            .select(
                "id,rss_url,category,category_id,"
                "categories!rss_category_id_fkey(name,visibility)"
            )
            .not_.is_("category_id", "null")
            .execute()
        )
        for row in legacy_response.data or []:
            category = _relation_one(row.get("categories"))
            if not category or category.get("visibility") != "public":
                continue
            rss_url = (row.get("rss_url") or "").strip()
            category_name = (
                category.get("name") or row.get("category") or "General"
            ).strip()
            key = (rss_url, category_name.casefold())
            if rss_url and key not in seen:
                seen.add(key)
                sources.append({
                    "rss_id": row.get("id"),
                    "rss_url": rss_url,
                    "category": category_name,
                })
    except Exception as exc:
        # Legacy lookup is optional; the primary category_sources query remains valid.
        print(f"ℹ️ Legacy RSS/category lookup skipped: {type(exc).__name__}: {exc}")

    print(f"📰 Loaded {len(sources)} public RSS/category associations.")
    return sources


def insert_news_cache(article, ai_headline, ai_summary):
    """Insert a processed public article into news_cache."""
    image_url = article.get("image_url")
    image_url = str(image_url).strip() if image_url else None
    data = {
        "category": article.get("category") or "General",
        "source": article.get("source"),
        "original_title": article.get("title") or article.get("original_title"),
        "ai_headline": ai_headline,
        "ai_summary": ai_summary,
        "link": article.get("link"),
        "image_url": image_url or None,
        "published_at": article.get("published_at"),
    }
    result = supabase.table("news_cache").insert(data).execute()
    saved = getattr(result, "data", None) or []
    print(
        f"💾 Shared cache insert: {'OK' if saved else 'no returned row'} | "
        f"image={'yes' if image_url else 'no'} | "
        f"{str(data['original_title'] or 'Untitled')[:80]}"
    )
    return result


def get_cached_news_for_categories(categories):
    if not categories:
        return []
    response = (
        supabase.table("news_cache")
        .select(ARTICLE_COLUMNS)
        .in_("category", categories)
        .execute()
    )
    return response.data or []


def is_cache_present():
    response = supabase.table("news_cache").select("id").limit(1).execute()
    return bool(response.data)


def clear_news_cache():
    """Clear shared cache; call only after a fresh collection succeeds."""
    return (
        supabase.table("news_cache")
        .delete()
        .not_.is_("id", "null")
        .execute()
    )


def clear_old_news_cache(hours=2):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return (
        supabase.table("news_cache")
        .delete()
        .lt("created_at", cutoff.isoformat())
        .execute()
    )


def get_user_selected_sources(user_id):
    """Resolve selected categories to RSS feeds through category_sources.

    user_category_sources is treated as the user's category-selection table.
    Public categories can be followed; private categories are owner-only.
    """
    selection_rows = (
        supabase.table("user_category_sources")
        .select(
            "category_id,"
            "categories!user_category_sources_category_id_fkey("
            "id,name,visibility,owner_id)"
        )
        .eq("user_id", user_id)
        .execute()
        .data or []
    )

    selected_categories = {}
    for row in selection_rows:
        category = _relation_one(row.get("categories"))
        if not category:
            continue
        visibility = category.get("visibility")
        if visibility == "private" and category.get("owner_id") != user_id:
            continue
        if visibility not in ("public", "private"):
            continue
        category_id = category.get("id") or row.get("category_id")
        if category_id:
            selected_categories[category_id] = {
                "name": category.get("name") or "General",
                "visibility": visibility,
            }

    if not selected_categories:
        print(f"⚠️ No accessible selected categories for user {user_id}.")
        return []

    association_rows = (
        supabase.table("category_sources")
        .select(
            "rss_id,category_id,"
            "rss!category_sources_rss_id_fkey(id,rss_url)"
        )
        .in_("category_id", list(selected_categories.keys()))
        .execute()
        .data or []
    )

    sources, seen = [], set()
    for row in association_rows:
        rss = _relation_one(row.get("rss"))
        if not rss:
            continue
        rss_id = rss.get("id") or row.get("rss_id")
        rss_url = (rss.get("rss_url") or "").strip()
        category_info = selected_categories.get(row.get("category_id"))
        if not rss_id or not rss_url or not category_info:
            continue
        key = (str(rss_id), category_info["name"].casefold())
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "rss_id": rss_id,
            "rss_url": rss_url,
            "category": category_info["name"],
            "visibility": category_info["visibility"],
        })

    print(f"📰 Resolved {len(sources)} selected RSS feeds for {user_id}.")
    return sources


def get_user_private_sources(user_id):
    """Return RSS feeds belonging to private categories owned by this user."""
    return [
        {key: value for key, value in source.items() if key != "visibility"}
        for source in get_user_selected_sources(user_id)
        if source.get("visibility") == "private"
    ]


def _fetch_cached_rows(table_name, rss_url, user_id=None):
    query = (
        supabase.table(table_name)
        .select(ARTICLE_COLUMNS)
        .eq("source", rss_url)
    )
    if table_name == "private_news_cache":
        if not user_id:
            return []
        query = query.eq("user_id", user_id)
    response = query.execute()
    return response.data or []


def get_news_from_user_sources(user_id, per_source=ARTICLES_PER_RSS):
    """Return the newest N cached articles per selected RSS source.

    Public feeds read news_cache. Private feeds read private_news_cache and
    news_cache. Article cache rows are matched by source URL because the
    current cache insert schema does not persist rss_id.
    """
    sources = get_user_selected_sources(user_id)
    if not sources:
        return []

    result = []
    for source in sources:
        rss_url = source["rss_url"]
        category = source["category"]
        visibility = source["visibility"]
        rows = []

        if visibility == "public":
            try:
                rows.extend(_fetch_cached_rows("news_cache", rss_url))
            except Exception as exc:
                print(f"❌ news_cache query failed for {rss_url}: {exc}")
        else:
            try:
                rows.extend(_fetch_cached_rows(
                    "private_news_cache", rss_url, user_id=user_id
                ))
            except Exception as exc:
                print(f"❌ private_news_cache query failed for {rss_url}: {exc}")
            try:
                rows.extend(_fetch_cached_rows("news_cache", rss_url))
            except Exception as exc:
                print(f"❌ news_cache query failed for {rss_url}: {exc}")

        rows.sort(
            key=lambda item: _published_datetime(item.get("published_at")),
            reverse=True,
        )

        # De-duplicate within this feed only, so one feed's items do not reduce
        # another feed's five-article allowance.
        feed_links = set()
        selected = []
        for row in rows:
            link = (row.get("link") or "").strip()
            if link and link in feed_links:
                continue
            if link:
                feed_links.add(link)
            selected.append({
                "category": row.get("category") or category,
                "ai_headline": row.get("ai_headline") or "",
                "original_title": row.get("original_title") or "",
                "ai_summary": row.get("ai_summary") or "",
                "link": link,
                "source": row.get("source") or rss_url,
                "image_url": row.get("image_url"),
                "published_at": row.get("published_at"),
                "rss_id": source["rss_id"],
                "rss_url": rss_url,
            })
            if len(selected) >= per_source:
                break

        print(
            f"🗞️ {category} | {rss_url}: "
            f"selected {len(selected)}/{per_source} cached articles."
        )
        result.extend(selected)

    print(f"📧 Total cached articles selected for {user_id}: {len(result)}")
    return result


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
