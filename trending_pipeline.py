"""News-based trending pipeline for Elinity.

Uses the existing trend_events, trend_sources and trend_snapshots tables.
This measures news coverage only, not social-media engagement.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from agents.trend_collector import fetch_trend_articles
from agents.trend_detector import event_key, published_at_or_now, score_event, similarity
from storage import get_all_sources
from supabase_client import supabase

EVENT_LOOKBACK_HOURS = 72
EVENT_MATCH_THRESHOLD = 0.38
PROGRESS_EVERY = 10
SOURCE_BATCH_SIZE = 100


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] {message}", flush=True)


def elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"


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
    events = result.data or []
    log(f"Loaded {len(events)} existing events for category '{category}'")
    return events


def _find_or_create_event(article: dict, event_cache: dict[str, list[dict]]) -> dict:
    category = article.get("category") or "General"
    if category not in event_cache:
        event_cache[category] = _recent_events(category)
    candidates = event_cache[category]

    best_event = None
    best_score = 0.0
    title = article["title"]
    for candidate in candidates:
        candidate_score = similarity(title, candidate.get("title", ""))
        if candidate_score > best_score:
            best_event = candidate
            best_score = candidate_score

    now = datetime.now(timezone.utc).isoformat()
    if best_event and best_score >= EVENT_MATCH_THRESHOLD:
        # Defer the database timestamp update until all articles are matched.
        best_event["last_seen"] = now
        return best_event

    key = event_key(title, category)
    insert_data = {
        "event_key": key,
        "title": title[:500],
        "category": category,
        "first_seen": now,
        "last_seen": now,
    }
    result = supabase.table("trend_events").insert(insert_data).execute()
    created = (result.data or [None])[0]

    # Keep fallback behavior for schemas/clients that don't return inserted rows.
    if not created:
        existing = (
            supabase.table("trend_events")
            .select("id,event_key,title,category,first_seen,last_seen")
            .eq("event_key", key)
            .limit(1)
            .execute()
        )
        created = (existing.data or [None])[0]

    if not created:
        raise RuntimeError(f"Could not create or retrieve trend event for: {title}")
    candidates.insert(0, created)
    return created


def _article_source_row(event: dict, article: dict, observed_at: str) -> dict:
    article_url = article.get("link")
    if not article_url:
        raise ValueError("Article has no URL")
    return {
        "event_id": event["id"],
        "article_url": article_url,
        "article_title": article["title"][:1000],
        "publisher": article.get("publisher") or "Unknown",
        "category": article.get("category") or "General",
        "published_at": published_at_or_now(article.get("published_at")),
        "observed_at": observed_at,
    }


def _save_sources_in_batches(rows: list[dict]) -> int:
    """Upsert article associations in batches instead of one request per article."""
    saved = 0
    for start in range(0, len(rows), SOURCE_BATCH_SIZE):
        batch = rows[start:start + SOURCE_BATCH_SIZE]
        if not batch:
            continue
        supabase.table("trend_sources").upsert(batch, on_conflict="article_url").execute()
        saved += len(batch)
        log(f"Saved source batch: {saved}/{len(rows)} rows")
    return saved


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
    recent_rows = []
    previous_rows = []
    for row in result.data or []:
        try:
            published_value = row["published_at"]
            published = datetime.fromisoformat(published_value.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published >= recent_start:
                recent_rows.append(row)
            else:
                previous_rows.append(row)
        except (KeyError, ValueError, TypeError, AttributeError):
            continue

    all_sources = (
        supabase.table("trend_sources")
        .select("publisher")
        .eq("event_id", event["id"])
        .limit(1000)
        .execute()
        .data or []
    )
    publisher_count = len({row["publisher"] for row in all_sources if row.get("publisher")})
    score, status = score_event(len(recent_rows), len(previous_rows), publisher_count)

    supabase.table("trend_events").update({
        "article_count": len(all_sources),
        "publisher_count": publisher_count,
        "news_score": score,
        "trend_status": status,
        "updated_at": now.isoformat(),
        "last_seen": now.isoformat(),
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
    pipeline_start = time.perf_counter()
    log("Starting Elinity news-based trending pipeline")

    stage_start = time.perf_counter()
    log("Loading RSS sources from Supabase...")
    sources = get_all_sources()
    log(f"Source loading completed in {elapsed(stage_start)}; {len(sources)} source records found")
    if not sources:
        log("No RSS sources found via user_sources. Nothing to process.")
        return

    stage_start = time.perf_counter()
    log("Fetching articles from RSS feeds...")
    articles = fetch_trend_articles(sources)
    log(f"RSS collection completed in {elapsed(stage_start)}; {len(articles)} articles collected")
    if not articles:
        log("No articles collected. Pipeline finished without changes.")
        return

    # Drop invalid URLs and repeated feed entries before doing database work.
    unique_articles = []
    seen_urls = set()
    for article in articles:
        url = article.get("link")
        if not url or url in seen_urls or not article.get("title"):
            continue
        seen_urls.add(url)
        unique_articles.append(article)
    log(f"Deduplicated articles: {len(articles)} -> {len(unique_articles)}")
    if not unique_articles:
        log("No valid unique articles to process.")
        return

    stage_start = time.perf_counter()
    event_cache: dict[str, list[dict]] = {}
    touched_events: dict[str, dict] = {}
    source_rows = []
    errors = 0
    observed_at = datetime.now(timezone.utc).isoformat()
    log(f"Matching {len(unique_articles)} articles to events...")

    for index, article in enumerate(unique_articles, start=1):
        try:
            event = _find_or_create_event(article, event_cache)
            touched_events[str(event["id"])] = event
            source_rows.append(_article_source_row(event, article, observed_at))
        except Exception as exc:
            errors += 1
            log(f"Article {index}/{len(unique_articles)} failed: {type(exc).__name__}: {exc}")
        if index % PROGRESS_EVERY == 0 or index == len(unique_articles):
            log(f"Matching progress: {index}/{len(unique_articles)}; rows={len(source_rows)}; errors={errors}; events={len(touched_events)}; elapsed={elapsed(stage_start)}")

    # One upsert per batch, rather than one request per article.
    saved = 0
    if source_rows:
        try:
            saved = _save_sources_in_batches(source_rows)
        except Exception as exc:
            errors += len(source_rows) - saved
            log(f"Batch source upsert failed: {type(exc).__name__}: {exc}")
            # Retry rows individually so one bad row doesn't discard the whole batch.
            for row in source_rows:
                try:
                    supabase.table("trend_sources").upsert(row, on_conflict="article_url").execute()
                    saved += 1
                except Exception as row_exc:
                    log(f"Source row failed ({row.get('article_url')}): {type(row_exc).__name__}: {row_exc}")

    log(f"Matching/source storage completed in {elapsed(stage_start)}; saved={saved}; errors={errors}")

    stage_start = time.perf_counter()
    events = list(touched_events.values())
    metric_errors = 0
    log(f"Refreshing metrics for {len(events)} events...")
    for index, event in enumerate(events, start=1):
        try:
            _refresh_event_metrics(event)
        except Exception as exc:
            metric_errors += 1
            log(f"Metrics failed for event {event.get('id')}: {type(exc).__name__}: {exc}")
        if index % PROGRESS_EVERY == 0 or index == len(events):
            log(f"Metrics progress: {index}/{len(events)}; errors={metric_errors}; elapsed={elapsed(stage_start)}")
    log(f"Metrics stage completed in {elapsed(stage_start)}")
    log(f"Trending pipeline finished. Articles collected={len(articles)}; unique={len(unique_articles)}; sources saved={saved}; article errors={errors}; events refreshed={len(events) - metric_errors}/{len(events)}; metric errors={metric_errors}; total_elapsed={elapsed(pipeline_start)}")


if __name__ == "__main__":
    run_trending_pipeline()