"""Separate scheduled pipeline for news-based trending in Elinity.

Prerequisite:
Run sql/trending_schema.sql in the Supabase SQL Editor.

This pipeline measures news coverage only. It does not represent X trends
or public social engagement until an authorized provider is integrated.
"""

from __future__ import annotations

import time
from collections import defaultdict
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
PROGRESS_EVERY = 10


def log(message: str) -> None:
    """Print immediately so GitHub Actions shows progress."""
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"[{timestamp}] {message}", flush=True)


def elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"


def _recent_events(category: str) -> list[dict]:
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=EVENT_LOOKBACK_HOURS)
    ).isoformat()

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


def _find_or_create_event(
    article: dict,
    event_cache: dict[str, list[dict]],
) -> dict:
    category = article.get("category") or "General"

    # IMPORTANT: do not use setdefault(category, _recent_events(category)).
    # Function arguments are evaluated on every call, even when the key
    # already exists. Load each category only once per pipeline run.
    if category not in event_cache:
        event_cache[category] = _recent_events(category)

    candidates = event_cache[category]

    best_event = None
    best_score = 0.0

    for candidate in candidates:
        candidate_score = similarity(
            article["title"],
            candidate.get("title", ""),
        )

        if candidate_score > best_score:
            best_event = candidate
            best_score = candidate_score

    now = datetime.now(timezone.utc).isoformat()

    if best_event and best_score >= EVENT_MATCH_THRESHOLD:
        # Refresh the existing event's last-seen timestamp.
        (
            supabase.table("trend_events")
            .update({"last_seen": now})
            .eq("id", best_event["id"])
            .execute()
        )

        best_event["last_seen"] = now
        return best_event

    key = event_key(article["title"], category)

    insert_data = {
        "event_key": key,
        "title": article["title"][:500],
        "category": category,
        "first_seen": now,
        "last_seen": now,
    }

    result = (
        supabase.table("trend_events")
        .insert(insert_data)
        .execute()
    )

    created = (result.data or [None])[0]

    if not created:
        existing = (
            supabase.table("trend_events")
            .select("id,event_key,title,category,first_seen,last_seen")
            .eq("event_key", key)
            .limit(1)
            .execute()
        )
        created = (existing.data or [None])[0]

    if created:
        candidates.insert(0, created)
        return created

    raise RuntimeError(
        f"Could not create or retrieve trend event for: {article['title']}"
    )


def _save_article(event: dict, article: dict) -> None:
    article_url = article.get("link")

    if not article_url:
        raise ValueError("Article has no URL")

    data = {
        "event_id": event["id"],
        "article_url": article_url,
        "article_title": article["title"][:1000],
        "publisher": article.get("publisher") or "Unknown",
        "category": article.get("category") or "General",
        "published_at": published_at_or_now(
            article.get("published_at")
        ),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }

    (
        supabase.table("trend_sources")
        .upsert(data, on_conflict="article_url")
        .execute()
    )


def _refresh_event_metrics(event: dict) -> None:
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(hours=2)
    previous_start = now - timedelta(hours=4)

    # Articles in the previous four hours, divided into two windows.
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
            published_value = row["published_at"]
            published = datetime.fromisoformat(
                published_value.replace("Z", "+00:00")
            )

            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)

            if published >= recent_start:
                recent_rows.append(row)
            else:
                previous_rows.append(row)

        except (KeyError, ValueError, TypeError):
            continue

    # Count articles and unique publishers for this event.
    all_sources = (
        supabase.table("trend_sources")
        .select("publisher")
        .eq("event_id", event["id"])
        .limit(1000)
        .execute()
        .data
        or []
    )

    publisher_count = len({
        row["publisher"]
        for row in all_sources
        if row.get("publisher")
    })

    score, status = score_event(
        len(recent_rows),
        len(previous_rows),
        publisher_count,
    )

    (
        supabase.table("trend_events")
        .update({
            "article_count": len(all_sources),
            "publisher_count": publisher_count,
            "news_score": score,
            "trend_status": status,
            "updated_at": now.isoformat(),
        })
        .eq("id", event["id"])
        .execute()
    )

    (
        supabase.table("trend_snapshots")
        .insert({
            "event_id": event["id"],
            "captured_at": now.isoformat(),
            "article_count": len(all_sources),
            "publisher_count": publisher_count,
            "articles_last_2h": len(recent_rows),
            "articles_prev_2h": len(previous_rows),
            "news_score": score,
            "trend_status": status,
        })
        .execute()
    )


def run_trending_pipeline() -> None:
    pipeline_start = time.perf_counter()

    log("Starting Elinity news-based trending pipeline")

    # Stage 1: Load RSS sources.
    stage_start = time.perf_counter()
    log("Loading RSS sources from Supabase...")

    sources = get_all_sources()

    log(
        f"Source loading completed in {elapsed(stage_start)}; "
        f"{len(sources)} source records found"
    )

    if not sources:
        log("No RSS sources found via user_sources. Nothing to process.")
        return

    # Stage 2: Fetch articles.
    stage_start = time.perf_counter()
    log("Fetching articles from RSS feeds...")

    articles = fetch_trend_articles(sources)

    log(
        f"RSS collection completed in {elapsed(stage_start)}; "
        f"{len(articles)} articles collected"
    )

    if not articles:
        log("No articles collected. Pipeline finished without changes.")
        return

    # Stage 3: Match articles to events and save article associations.
    stage_start = time.perf_counter()

    event_cache: dict[str, list[dict]] = {}
    touched_events: dict[str, dict] = {}
    errors = 0
    saved = 0

    log(f"Matching and storing {len(articles)} articles...")

    for index, article in enumerate(articles, start=1):
        try:
            event = _find_or_create_event(article, event_cache)
            _save_article(event, article)

            touched_events[event["id"]] = event
            saved += 1

        except Exception as exc:
            errors += 1
            log(
                f"Article {index}/{len(articles)} failed: "
                f"{type(exc).__name__}: {exc}"
            )

        if index % PROGRESS_EVERY == 0 or index == len(articles):
            log(
                f"Article progress: {index}/{len(articles)}; "
                f"saved={saved}; errors={errors}; "
                f"events={len(touched_events)}; "
                f"stage_elapsed={elapsed(stage_start)}"
            )

    log(
        f"Article matching completed in {elapsed(stage_start)}"
    )

    # Stage 4: Refresh metrics and store trend snapshots.
    stage_start = time.perf_counter()
    total_events = len(touched_events)
    metric_errors = 0

    log(f"Refreshing metrics for {total_events} events...")

    for index, event in enumerate(touched_events.values(), start=1):
        try:
            _refresh_event_metrics(event)

        except Exception as exc:
            metric_errors += 1
            log(
                f"Metrics failed for event {event.get('id')}: "
                f"{type(exc).__name__}: {exc}"
            )

        if index % PROGRESS_EVERY == 0 or index == total_events:
            log(
                f"Metrics progress: {index}/{total_events}; "
                f"errors={metric_errors}; "
                f"stage_elapsed={elapsed(stage_start)}"
            )

    log(f"Metrics stage completed in {elapsed(stage_start)}")

    log(
        "Trending pipeline finished. "
        f"Articles saved={saved}/{len(articles)}; "
        f"article errors={errors}; "
        f"events refreshed={total_events - metric_errors}/{total_events}; "
        f"metric errors={metric_errors}; "
        f"total_elapsed={elapsed(pipeline_start)}"
    )


if __name__ == "__main__":
    run_trending_pipeline()