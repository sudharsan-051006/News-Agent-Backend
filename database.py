"""
Database Layer for AI News Trend Radar Agent.
Powered by Neon Serverless PostgreSQL with SSL.
Maintains 6-day rolling memory baseline, articles, topic snapshots, and audit logs.
"""

import os
import json
import logging
import time
import functools
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from config import settings

logger = logging.getLogger("agent.database")


def db_retry(max_retries: int = 3, delay: float = 1.0):
    """
    Decorator to retry database operations on transient connection drops,
    TCP timeouts, or Neon serverless pooler reconnects.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                    if attempt == max_retries:
                        logger.error(f"Neon DB operation '{func.__name__}' failed after {max_retries} attempts: {e}")
                        raise
                    logger.warning(
                        f"Transient Neon DB connection drop in '{func.__name__}' "
                        f"(attempt {attempt}/{max_retries}): {e}. Reconnecting in {delay * attempt:.1f}s..."
                    )
                    time.sleep(delay * attempt)
        return wrapper
    return decorator


def get_connection():
    """Establishes connection to Neon PostgreSQL using SSL and TCP keepalives."""
    return psycopg2.connect(
        settings.DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=15,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5
    )


def init_db():
    """Initializes schema and tables in Neon DB."""
    schema_sql = """
    -- 1. RSS Feeds Catalog
    CREATE TABLE IF NOT EXISTS feeds (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        url TEXT UNIQUE NOT NULL,
        category VARCHAR(100) DEFAULT 'General Tech',
        reliability_score REAL DEFAULT 1.0, -- Dynamic feed weight (0.1 to 2.0)
        is_active BOOLEAN DEFAULT TRUE,
        last_fetched_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- 2. Raw & Cleaned Articles
    CREATE TABLE IF NOT EXISTS articles (
        id SERIAL PRIMARY KEY,
        feed_id INTEGER REFERENCES feeds(id) ON DELETE CASCADE,
        guid TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        published_at TIMESTAMPTZ,
        cleaned_content TEXT,
        primary_topic VARCHAR(150),
        keywords TEXT[],
        is_processed BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- 3. 6-Day Rolling Topic Snapshots (Stores ALL discovered topics for longitudinal memory)
    CREATE TABLE IF NOT EXISTS topic_snapshots (
        id SERIAL PRIMARY KEY,
        topic_name VARCHAR(255) NOT NULL,
        scope VARCHAR(20) DEFAULT 'GLOBAL', -- 'INDIA' or 'GLOBAL'
        keywords TEXT[],
        article_count INTEGER DEFAULT 1,
        snapshot_date DATE NOT NULL,
        trend_type VARCHAR(50), -- 'BREAKOUT', 'EMERGING', 'EVOLVING', 'SEED_MENTION'
        velocity_score REAL DEFAULT 1.0,
        summary TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(topic_name, snapshot_date)
    );

    -- 4. Agentic Decision & Audit Log
    CREATE TABLE IF NOT EXISTS audit_logs (
        id SERIAL PRIMARY KEY,
        run_date TIMESTAMPTZ DEFAULT NOW(),
        decision VARCHAR(50) NOT NULL, -- 'DISPATCHED' or 'SUPPRESSED_LOW_SIGNAL'
        critic_score REAL,
        critic_feedback TEXT,
        email_subject TEXT,
        top_trend VARCHAR(255),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- 5. Workflow State Checkpoints (Resumable Execution)
    CREATE TABLE IF NOT EXISTS workflow_checkpoints (
        id SERIAL PRIMARY KEY,
        run_date DATE NOT NULL DEFAULT CURRENT_DATE,
        step_name VARCHAR(50) NOT NULL,
        output_data TEXT NOT NULL,
        status VARCHAR(20) DEFAULT 'COMPLETED',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(run_date, step_name)
    );

    -- Migration check: Ensure new columns exist on topic_snapshots
    ALTER TABLE topic_snapshots ADD COLUMN IF NOT EXISTS scope VARCHAR(20) DEFAULT 'GLOBAL';
    ALTER TABLE topic_snapshots ADD COLUMN IF NOT EXISTS keywords TEXT[];
    ALTER TABLE topic_snapshots ADD COLUMN IF NOT EXISTS pillar VARCHAR(100) DEFAULT 'General News';
    ALTER TABLE topic_snapshots ADD COLUMN IF NOT EXISTS why_trending TEXT;
    ALTER TABLE topic_snapshots ADD COLUMN IF NOT EXISTS image_url TEXT;
    ALTER TABLE topic_snapshots ADD COLUMN IF NOT EXISTS reference_articles JSONB DEFAULT '[]'::jsonb;
    ALTER TABLE articles ADD COLUMN IF NOT EXISTS image_url TEXT;

    -- Indexes for high-speed rolling window queries
    CREATE INDEX IF NOT EXISTS idx_articles_created_at ON articles(created_at);
    CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(primary_topic);
    CREATE INDEX IF NOT EXISTS idx_topic_snapshots_date ON topic_snapshots(snapshot_date);
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            conn.commit()
            logger.info("Neon PostgreSQL schema initialized successfully.")


def sync_feeds_from_config(config_path: str = "feeds.json"):
    """
    Synchronizes the Neon DB feeds table with feeds.json.
    - Reads all feed URLs from feeds.json (clean, simple name + url list).
    - Inserts new feeds or reactivates existing ones.
    - Automatically deactivates feeds removed from feeds.json (without deleting article history).
    - Category is completely optional: AI dynamically classifies all articles!
    """
    file_path = os.path.join(os.path.dirname(__file__), config_path)
    if not os.path.exists(file_path):
        file_path = config_path

    if not os.path.exists(file_path):
        logger.warning(f"Feeds config '{config_path}' not found. Seeding defaults.")
        default_feeds = [
            ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
            ("Hacker News Top", "https://hnrss.org/frontpage"),
            ("BBC World News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
            ("Foreign Policy", "https://foreignpolicy.com/feed/"),
            ("Al Jazeera World", "https://www.aljazeera.com/xml/rss/all.xml"),
            ("The Hindu National", "https://www.thehindu.com/news/national/feeder/default.rss"),
            ("Indian Express", "https://indianexpress.com/section/india/feed/"),
            ("LiveMint Policy", "https://www.livemint.com/rss/politics"),
            ("Economic Times Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
            ("LiveMint Markets", "https://www.livemint.com/rss/markets"),
            ("Yahoo Finance News", "https://finance.yahoo.com/news/rssindex")
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([{"name": n, "url": u} for n, u in default_feeds], f, indent=2)

    with open(file_path, "r", encoding="utf-8") as f:
        configured = json.load(f)

    active_urls = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            for item in configured:
                name = item.get("name", "News Feed").strip()
                url = item.get("url", "").strip()
                category = item.get("category", "General News")
                if not url:
                    continue
                active_urls.append(url)
                cur.execute("""
                    INSERT INTO feeds (name, url, category, is_active)
                    VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT (url) DO UPDATE SET
                        name = EXCLUDED.name,
                        is_active = TRUE;
                """, (name, url, category))

            if active_urls:
                cur.execute("""
                    UPDATE feeds 
                    SET is_active = FALSE 
                    WHERE url NOT IN %s;
                """, (tuple(active_urls),))

            conn.commit()
            logger.info(f"Synchronized feeds catalog: {len(active_urls)} active feeds from {config_path}.")


def sync_feeds_from_supabase() -> int:
    """
    Synchronizes the Neon DB feeds table directly from the Supabase `rss` table
    (project atonkzxonfemlctmtdvo).
    - Fetches all user/admin RSS feeds configured in Supabase.
    - Automatically inserts new feeds into Neon DB or marks them active.
    - Category from Supabase is purely informational; the AI independently
      determines the true story pillar and event classification.
    - Falls back to local feeds.json if Supabase is unreachable.
    """
    import httpx
    supabase_url = settings.SUPABASE_URL.rstrip('/')
    supabase_key = settings.SUPABASE_KEY

    if not supabase_key:
        logger.info("No SUPABASE_KEY provided. Falling back to feeds.json.")
        sync_feeds_from_config("feeds.json")
        return 0

    endpoint = f"{supabase_url}/rest/v1/rss?select=id,name,rss_url,category"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}"
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(endpoint, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch Supabase rss table (HTTP {resp.status_code}): {resp.text}. Falling back to feeds.json.")
                sync_feeds_from_config("feeds.json")
                return 0
            
            supabase_rows = resp.json()
            if not supabase_rows:
                logger.info("Supabase rss table returned 0 rows. Falling back to feeds.json.")
                sync_feeds_from_config("feeds.json")
                return 0

            active_urls = []
            with get_connection() as conn:
                with conn.cursor() as cur:
                    for row in supabase_rows:
                        name = (row.get("name") or "News Source").strip()
                        url = (row.get("rss_url") or "").strip()
                        cat = row.get("category") or "General"
                        if not url:
                            continue
                        active_urls.append(url)
                        cur.execute("""
                            INSERT INTO feeds (name, url, category, is_active)
                            VALUES (%s, %s, %s, TRUE)
                            ON CONFLICT (url) DO UPDATE SET
                                name = EXCLUDED.name,
                                category = EXCLUDED.category,
                                is_active = TRUE;
                        """, (name, url, cat))

                    if active_urls:
                        cur.execute("""
                            UPDATE feeds 
                            SET is_active = FALSE 
                            WHERE url NOT IN %s;
                        """, (tuple(active_urls),))

                    conn.commit()

            logger.info(f"Successfully synced {len(active_urls)} RSS feeds directly from Supabase project into Neon DB.")
            return len(active_urls)

    except Exception as e:
        logger.error(f"Error connecting to Supabase: {e}. Falling back to feeds.json.")
        sync_feeds_from_config("feeds.json")
        return 0


def seed_default_feeds():
    """Syncs from Supabase rss table with fallback to feeds.json."""
    count = sync_feeds_from_supabase()
    if count == 0:
        sync_feeds_from_config("feeds.json")


def get_active_feeds() -> List[Dict[str, Any]]:
    """Returns all active feeds ordered by reliability score."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, url, category, reliability_score
                FROM feeds
                WHERE is_active = TRUE
                ORDER BY reliability_score DESC;
            """)
            return list(cur.fetchall())


@db_retry(max_retries=3, delay=1.0)
def get_existing_guids(feed_id: int) -> set:
    """Returns set of all existing GUIDs for a feed in a single query."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT guid FROM articles WHERE feed_id = %s;", (feed_id,))
            return {r["guid"] for r in cur.fetchall()}


@db_retry(max_retries=3, delay=1.0)
def article_exists(guid: str) -> bool:
    """Checks if an article GUID has already been ingested into Neon DB."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM articles WHERE guid = %s LIMIT 1;", (guid,))
            return cur.fetchone() is not None


@db_retry(max_retries=3, delay=1.0)
def insert_article(feed_id: int, guid: str, title: str, url: str, 
                   published_at: Optional[datetime], cleaned_content: str,
                   image_url: str = "",
                   primary_topic: str = "", keywords: List[str] = None) -> bool:
    """Inserts a new article with optional image_url. Returns True if inserted, False if already existed."""
    if keywords is None:
        keywords = []
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO articles 
                (feed_id, guid, title, url, published_at, cleaned_content, image_url, primary_topic, keywords)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (guid) DO UPDATE SET
                    image_url = CASE WHEN EXCLUDED.image_url <> '' THEN EXCLUDED.image_url ELSE articles.image_url END
                RETURNING id;
            """, (feed_id, guid, title, url, published_at, cleaned_content, image_url, primary_topic, keywords))
            row = cur.fetchone()
            conn.commit()
            return row is not None


@db_retry(max_retries=3, delay=1.0)
def get_six_day_topic_baseline() -> Dict[str, float]:
    """
    Computes average daily mention count for each topic over the previous 6 days
    (from yesterday backwards 6 days).
    Returns: { topic_name: average_daily_count }
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    topic_name,
                    ROUND(AVG(article_count)::numeric, 2) AS avg_daily_count,
                    COUNT(snapshot_date) AS active_days
                FROM topic_snapshots
                WHERE snapshot_date >= CURRENT_DATE - INTERVAL '6 days'
                  AND snapshot_date < CURRENT_DATE
                GROUP BY topic_name;
            """)
            rows = cur.fetchall()
            return {r["topic_name"]: float(r["avg_daily_count"]) for r in rows}


@db_retry(max_retries=3, delay=1.0)
def record_topic_snapshot(topic_name: str, count: int, trend_type: str, 
                          velocity_score: float, scope: str = "GLOBAL", 
                          keywords: List[str] = None, summary: str = "",
                          pillar: str = "General News", why_trending: str = "",
                          image_url: str = "", reference_articles: List[Dict[str, Any]] = None):
    """Records EVERY discovered topic snapshot into Neon DB with rich metadata, why_trending, and source links."""
    if keywords is None:
        keywords = []
    if not reference_articles or len(reference_articles) == 0:
        logger.info(f"Skipping topic snapshot '{topic_name}' - 0 reference articles provided.")
        return
        
    import re

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check for existing similar topic from today to merge coverage instead of duplicating
            cur.execute("""
                SELECT id, topic_name, article_count, velocity_score, reference_articles, image_url
                FROM topic_snapshots
                WHERE snapshot_date = CURRENT_DATE;
            """)
            today_rows = cur.fetchall()
            
            t_words = set(re.findall(r"\w+", topic_name.lower()))
            t_words = {w for w in t_words if len(w) > 3 and w not in ["news", "today", "report", "says", "amid", "with", "after"]}
            
            match_row = None
            for tr in today_rows:
                tr_words = set(re.findall(r"\w+", tr["topic_name"].lower()))
                tr_words = {w for w in tr_words if len(w) > 3 and w not in ["news", "today", "report", "says", "amid", "with", "after"]}
                overlap = len(t_words & tr_words) / len(t_words | tr_words) if (t_words | tr_words) else 0
                if overlap >= 0.35:
                    match_row = tr
                    break

            if match_row:
                # Merge into existing topic
                existing_refs = match_row["reference_articles"] if isinstance(match_row["reference_articles"], list) else []
                existing_urls = {r.get("url") for r in existing_refs if isinstance(r, dict)}
                for r in reference_articles:
                    if isinstance(r, dict) and r.get("url") and r.get("url") not in existing_urls:
                        existing_refs.append(r)
                        existing_urls.add(r.get("url"))

                merged_count = match_row["article_count"] + count
                merged_img = image_url if image_url else (match_row["image_url"] or "")
                chosen_title = topic_name if len(topic_name) > len(match_row["topic_name"]) else match_row["topic_name"]

                cur.execute("""
                    UPDATE topic_snapshots
                    SET topic_name = %s,
                        article_count = %s,
                        reference_articles = %s,
                        image_url = CASE WHEN %s <> '' THEN %s ELSE image_url END,
                        pillar = CASE WHEN %s <> 'General News' THEN %s ELSE pillar END,
                        velocity_score = GREATEST(velocity_score, %s)
                    WHERE id = %s;
                """, (chosen_title, merged_count, json.dumps(existing_refs, default=str), merged_img, merged_img, pillar, pillar, velocity_score, match_row["id"]))
                conn.commit()
                return

            # If no existing topic match, insert fresh row
            cur.execute("""
                INSERT INTO topic_snapshots 
                (topic_name, scope, keywords, article_count, snapshot_date, trend_type, velocity_score, summary, pillar, why_trending, image_url, reference_articles)
                VALUES (%s, %s, %s, %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (topic_name, snapshot_date) DO UPDATE SET
                    scope = EXCLUDED.scope,
                    keywords = EXCLUDED.keywords,
                    article_count = EXCLUDED.article_count,
                    trend_type = EXCLUDED.trend_type,
                    velocity_score = EXCLUDED.velocity_score,
                    summary = EXCLUDED.summary,
                    pillar = EXCLUDED.pillar,
                    why_trending = EXCLUDED.why_trending,
                    image_url = CASE WHEN EXCLUDED.image_url <> '' THEN EXCLUDED.image_url ELSE topic_snapshots.image_url END,
                    reference_articles = EXCLUDED.reference_articles;
            """, (topic_name, scope, keywords, count, trend_type, velocity_score, summary, pillar, why_trending, image_url, json.dumps(reference_articles, default=str)))
            conn.commit()


@db_retry(max_retries=3, delay=1.0)
def get_recent_articles(hours: int = 24) -> List[Dict[str, Any]]:
    """
    Fetches articles from Neon DB balanced across all active feed sources (up to 10 per feed)
    so every publisher gets fair representation, while the AI independently classifies the topic domain.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH ranked_articles AS (
                    SELECT 
                        a.id, a.guid, a.title, a.url, a.published_at, a.cleaned_content as content, 
                        a.primary_topic, a.image_url, f.name as feed_name,
                        ROW_NUMBER() OVER (PARTITION BY a.feed_id ORDER BY a.created_at DESC) as rank_per_feed
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                    WHERE a.created_at >= NOW() - INTERVAL '%s hours'
                      AND f.is_active = TRUE
                )
                SELECT guid, title, url, published_at, content, primary_topic, image_url, feed_name
                FROM ranked_articles
                WHERE rank_per_feed <= 10
                ORDER BY published_at DESC NULLS LAST;
            """, (hours,))
            return list(cur.fetchall())


def get_checkpoint(step_name: str) -> Optional[str]:
    """Retrieves saved output for a workflow step completed today."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT output_data 
                FROM workflow_checkpoints 
                WHERE run_date = CURRENT_DATE AND step_name = %s AND status = 'COMPLETED'
                LIMIT 1;
            """, (step_name,))
            row = cur.fetchone()
            return row["output_data"] if row else None


def save_checkpoint(step_name: str, output_data: str):
    """Saves the output of a completed workflow step for today's run."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO workflow_checkpoints (run_date, step_name, output_data, status)
                VALUES (CURRENT_DATE, %s, %s, 'COMPLETED')
                ON CONFLICT (run_date, step_name) DO UPDATE SET
                    output_data = EXCLUDED.output_data,
                    status = 'COMPLETED',
                    created_at = NOW();
            """, (step_name, output_data))
            conn.commit()


def clear_today_checkpoints():
    """Clears today's checkpoints for a fresh, forced re-run."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM workflow_checkpoints WHERE run_date = CURRENT_DATE;")
            conn.commit()


def log_audit_decision(decision: str, critic_score: float, critic_feedback: str,
                       email_subject: str = "", top_trend: str = ""):
    """Records the agent's autonomous Go/No-Go decision and critic score."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO audit_logs 
                (decision, critic_score, critic_feedback, email_subject, top_trend)
                VALUES (%s, %s, %s, %s, %s);
            """, (decision, critic_score, critic_feedback, email_subject, top_trend))
            conn.commit()
