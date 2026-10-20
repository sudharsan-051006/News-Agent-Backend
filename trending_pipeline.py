"""Separate scheduled pipeline for news-based trending in Elinity.

Prerequisite: run sql/trending_schema.sql in the Supabase SQL Editor.
This MVP uses RSS coverage only. It does not represent X trends or public
social engagement until an authorized provider is integrated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.trend_collector import fetch_trend_articles
from agents.trend_detector import (
    event_key,
    published_at_or_now,
    score_event,
    similarity,
)
from storage import get_all_sources
from supabase_client import supabase

EVENT_LOOKBACK_HOURS = 72
EVENT_MATCH_THRESHOLD = 0.38


def _recent_events(category: str) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=EVENT_LOOKBACK_HOURS)).isoformat()
    result = (
        supabase.table("trend_events")
        .select("id,event_key,title,category,first_seen,last_seen")
        .eq("category", category)
        .gte("last_seen", cutoff)
        .order("last_seen", desc=True)
        .limit(300)
        .execute()
    )
    return result.data or []


def _find_or_create_event(article: dict, event_cache: dict[str, list[dict]]) -> dict:
    category = article.get("category") or "General"
    candidates = event_cache.setdefault(category, _recent_events(category))
    best_event = None
    best_score = 0.0
    for candidate in candidates:
        score = similarity(article["title"], candidate.get("title", ""))
        if score > best_score:
            best_event, best_score = candidate, score

    now = datetime.now(timezone.utc).isoformat()
    if best_event and best_score >= EVENT_MATCH_THRESHOLD:
        # Keep the existing representative title; refresh last_seen.
        supabase.table("trend_events").update({"last_seen": now}).eq("id", best_event["id"]).execute()
        best_event["last_seen"] = now
        return best_event

    key = event_key(article["title"], category)
    # Avoid event-key collisions when similar title tokens appear outside the matcher.
    insert = {
        "event_key": key,
        "title": article["title"][:500],
        "category": category,
        "first_seen": now,
        "last_seen": now,
    }
    result = supabase.table("trend_events").insert(insert).execute()
    created = (result.data or [None])[0]
    if not created:
        # A key collision may be caused by a prior run; fetch the matching row.
        existing = supabase.table("trend_events").select("id,event_key,title,category,first_seen,last_seen").eq("event_key", key).limit(1).execute()
        created = (existing.data or [None])[0]
    if created:
        candidates.insert(0, created)
        return created
    raise RuntimeError(f"Could not create or retrieve trend event for: {article['title']}")


def _save_article(event: dict, article: dict) -> None:
    data = {
        "event_id": event["id"],
        "article_url": article["link"],
        "article_title": article["title"][:1000],
        "publisher": article["publisher"],
        "category": article["category"],
        "published_at": published_at_or_now(article.get("published_at")),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase.table("trend_sources").upsert(data, on_conflict="article_url").execute()


def _refresh_event_metrics(event: dict) -> None:
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(hours=2)
    previous_start = now - timedelta(hours=4)

    result = (
        supabase.table("trend_sources")
        .select("publisher,published_at")
        .eq("event_id", event["id"])
        .gte("published_at", previous_start.isoformat())
        .lt("published_at", now.isoformat())
        .limit(1000)
        .execute()
    )
    rows = result.data or []
    recent_rows = []
    previous_rows = []
    for row in rows:
        try:
            published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published >= recent_start:
                recent_rows.append(row)
            else:
                previous_rows.append(row)
        except (KeyError, ValueError, TypeError):
            continue

    all_sources = (
        supabase.table("trend_sources")
        .select("publisher")
        .eq("event_id", event["id"])
        .limit(1000)
        .execute()
        .data or []
    )
    publisher_count = len({row.get("publisher") for row in all_sources if row.get("publisher")})
    # Unique articles are enforced by article_url; use the two recent windows for momentum.
    score, status = score_event(len(recent_rows), len(previous_rows), publisher_count)
    supabase.table("trend_events").update({
        "article_count": len(all_sources),
        "publisher_count": publisher_count,
        "news_score": score,
        "trend_status": status,
        "updated_at": now.isoformat(),
    }).eq("id", event["id"]).execute()
    supabase.table("trend_snapshots").insert({
        "event_id": event["id"],
        "captured_at": now.isoformat(),
        "article_count": len(all_sources),
        "publisher_count": publisher_count,
        "articles_last_2h": len(recent_rows),
        "articles_prev_2h": len(previous_rows),
        "news_score": score,
        "trend_status": status,
    }).execute()


def run_trending_pipeline() -> None:
    print("🚀 Starting Elinity news-based trending pipeline")
    sources = get_all_sources()
    if not sources:
        print("⚠️ No RSS sources found via user_sources; no trend collection performed.")
        return

    articles = fetch_trend_articles(sources)
    event_cache: dict[str, list[dict]] = {}
    touched_events: dict[str, dict] = {}
    saved = 0

    for article in articles:
        try:
            event = _find_or_create_event(article, event_cache)
            _save_article(event, article)
            touched_events[event["id"]] = event
            saved += 1
        except Exception as exc:
            print(f"⚠️ Could not store trend article {article.get('link', '')}: {type(exc).__name__}: {exc}")

    for event in touched_events.values():
        try:
            _refresh_event_metrics(event)
        except Exception as exc:
            print(f"⚠️ Could not refresh trend metrics for {event.get('title', '')[:80]}: {type(exc).__name__}: {exc}")

    print(f"✅ Trending pipeline complete: {saved}/{len(articles)} articles linked to events; {len(touched_events)} events refreshed.")


if __name__ == "__main__":
    run_trending_pipeline()
