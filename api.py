"""
FastAPI Backend Application for Elinity AI News Trend Radar Agent.
Provides:
- Secure Trends API (eliminating direct frontend database queries)
- Background Live RSS Sampling & Trend Recalculation
- Health Check
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware

from database import get_connection, db_retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("elinity.api")

app = FastAPI(
    title="Elinity News Trend Radar API",
    version="1.0.0",
    description="Backend API powering real-time news trend aggregation and scoring."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_scheduler = None


@app.on_event("startup")
def on_startup():
    """Initializes schemas on API startup and launches background RSS polling."""
    global api_scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from main import job_sample_and_update_trends
        api_scheduler = BackgroundScheduler()
        # Periodically sample active RSS feeds every 2 hours while API is running
        api_scheduler.add_job(
            job_sample_and_update_trends,
            'interval',
            hours=2,
            id='api_background_rss_job'
        )
        api_scheduler.start()
        logger.info("Background RSS sampling scheduler started (interval: 2 hours).")
    except Exception as exc:
        logger.warning(f"Background scheduler notice: {exc}")


@app.on_event("shutdown")
def on_shutdown():
    global api_scheduler
    if api_scheduler and api_scheduler.running:
        api_scheduler.shutdown()
        logger.info("Background RSS scheduler stopped.")


# =====================================================================
# Health Check
# =====================================================================

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Elinity News Trend Radar"}


# =====================================================================
# Trends Proxy API
# =====================================================================

@app.get("/api/trends")
def get_trends(limit: int = Query(60, ge=1, le=100)):
    """
    Secure endpoint proxying topic snapshots directly from Neon PostgreSQL.
    Allows frontend to fetch trends without exposing database connection strings.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    t.id,
                    t.topic_name,
                    t.scope,
                    t.pillar,
                    t.why_trending,
                    t.keywords,
                    t.article_count,
                    t.trend_type,
                    t.velocity_score,
                    t.summary,
                    t.image_url as topic_image,
                    t.reference_articles,
                    t.created_at
                FROM topic_snapshots t
                WHERE jsonb_array_length(CASE WHEN jsonb_typeof(t.reference_articles::jsonb) = 'array' THEN t.reference_articles::jsonb ELSE '[]'::jsonb END) > 0
                ORDER BY t.created_at DESC, t.velocity_score DESC
                LIMIT %s;
            """, (limit,))
            rows = list(cur.fetchall())
            return {"count": len(rows), "trends": rows}


@app.post("/api/trends/refresh")
def refresh_trends(background_tasks: BackgroundTasks):
    """
    Triggers immediate on-demand ingestion of active RSS feeds and recalculates topic trends.
    """
    from main import job_sample_and_update_trends
    background_tasks.add_task(job_sample_and_update_trends)
    return {"status": "started", "message": "Live RSS feed polling and trend update initiated in background."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
