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


def _refresh_metrics_with_rpc(events: list[dict]) -> tuple[int, int]:
    """Aggregate metrics in PostgreSQL and save event updates/snapshots in one RPC."""
    if not events:
        return 0, 0

    now = datetime.now(timezone.utc)
    event_ids = [str(event["id"]) for event in events]
    result = supabase.rpc(
        "get_trend_event_metrics",
        {"p_event_ids": event_ids},
    ).execute()
    metrics_by_id = {str(row["event_id"]): row for row in (result.data or [])}

    payload = []
    missing = 0
    for event_id in event_ids:
        row = metrics_by_id.get(event_id)
        if row is None:
            missing += 1
            log(f"No metrics returned for event {event_id}; skipping")
            continue

        recent_count = int(row.get("articles_last_2h") or 0)
        previous_count = int(row.get("articles_prev_2h") or 0)
        publisher_count = int(row.get("publisher_count") or 0)
        article_count = int(row.get("article_count") or 0)
        score, status = score_event(recent_count, previous_count, publisher_count)
        payload.append({
            "event_id": event_id,
            "article_count": article_count,
            "publisher_count": publisher_count,
            "articles_last_2h": recent_count,
            "articles_prev_2h": previous_count,
            "news_score": score,
            "trend_status": status,
            "updated_at": now.isoformat(),
            "last_seen": now.isoformat(),
            "captured_at": now.isoformat(),
        })

    if payload:
        supabase.rpc("save_trend_event_metrics", {"p_metrics": payload}).execute()
    return len(payload), missing


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
    refreshed = 0
    log(f"Refreshing metrics for {len(events)} events with PostgreSQL RPC...")
    try:
        refreshed, missing = _refresh_metrics_with_rpc(events)
        metric_errors += missing
        log(f"Metrics RPC completed; refreshed={refreshed}/{len(events)}; missing={missing}")
    except Exception as exc:
        metric_errors = len(events)
        log(f"Metrics RPC failed: {type(exc).__name__}: {exc}")
        raise
    log(f"Metrics stage completed in {elapsed(stage_start)}")
    log(f"Trending pipeline finished. Articles collected={len(articles)}; unique={len(unique_articles)}; sources saved={saved}; article errors={errors}; events refreshed={refreshed}/{len(events)}; metric errors={metric_errors}; total_elapsed={elapsed(pipeline_start)}")


if __name__ == "__main__":
    run_trending_pipeline()
