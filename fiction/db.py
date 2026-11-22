"""
Database Access Layer for Elinity Fiction Engine.
Integrates directly with Neon PostgreSQL using database.py connection pooling.
"""

import os
import json
import uuid
import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_connection, db_retry

logger = logging.getLogger("fiction.db")


def init_fiction_db():
    """Applies migration 001_fiction_engine.sql safely."""
    migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations", "001_fiction_engine.sql")
    if not os.path.exists(migration_path):
        logger.error(f"Migration file not found at {migration_path}")
        return False

    with open(migration_path, "r", encoding="utf-8") as f:
        sql = f.read()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
    logger.info("Fiction Engine database schema initialized successfully.")
    return True


# =====================================================================
# Article Retrieval & Eligibility Filter
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def get_eligible_articles(days: int = 7, min_words: int = 40, limit: int = 150) -> List[Dict[str, Any]]:
    """
    Retrieves high-quality articles from Neon DB within the configured time window.
    Applies eligibility filter:
    - Excludes empty or near-empty content.
    - Excludes articles already extracted if needed.
    - Orders by published_at DESC.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    a.id, a.guid, a.title, a.url, a.published_at, 
                    a.cleaned_content, a.primary_topic, a.keywords, a.image_url,
                    f.name as publisher
                FROM articles a
                LEFT JOIN feeds f ON a.feed_id = f.id
                WHERE a.published_at >= NOW() - INTERVAL '%s days'
                  AND a.cleaned_content IS NOT NULL
                  AND LENGTH(TRIM(a.cleaned_content)) >= %s
                ORDER BY a.published_at DESC
                LIMIT %s;
            """, (days, min_words * 5, limit))
            return list(cur.fetchall())


# =====================================================================
# Events & Provenance
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def insert_fiction_event(
    event_type: str,
    title: str,
    description: str,
    main_action: str = "",
    event_date: Optional[date] = None,
    date_precision: str = "EXACT",
    location: str = "",
    country: str = "",
    topics: List[str] = None,
    extraction_confidence: float = 0.8
) -> int:
    """Inserts a structured real-world event record."""
    topics = topics or []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_events
                (event_type, title, description, main_action, event_date, date_precision, location, country, topics, extraction_confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (event_type, title, description, main_action, event_date, date_precision, location, country, topics, extraction_confidence))
            event_id = cur.fetchone()["id"]
            conn.commit()
            return event_id


@db_retry(max_retries=3, delay=1.0)
def insert_event_source(
    event_id: int,
    article_id: Optional[int],
    source_url: str,
    evidence_excerpt: str,
    publisher: str = "",
    published_at: Optional[datetime] = None
) -> int:
    """Stores provenance linking an event to its source news article."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_event_sources
                (event_id, article_id, source_url, evidence_excerpt, publisher, published_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id, article_id) DO UPDATE SET
                    evidence_excerpt = EXCLUDED.evidence_excerpt
                RETURNING id;
            """, (event_id, article_id, source_url, evidence_excerpt, publisher, published_at))
            source_id = cur.fetchone()["id"]
            conn.commit()
            return source_id


@db_retry(max_retries=3, delay=1.0)
def get_all_events(limit: int = 100, offset: int = 0, topic: Optional[str] = None, country: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves extracted events with source provenance and entities."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT 
                    e.id, e.event_type, e.title, e.description, e.main_action,
                    e.event_date, e.date_precision, e.location, e.country, e.topics,
                    e.extraction_confidence, e.created_at,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'article_id', s.article_id,
                        'source_url', s.source_url,
                        'publisher', s.publisher,
                        'evidence_excerpt', s.evidence_excerpt,
                        'published_at', s.published_at
                    )) FILTER (WHERE s.id IS NOT NULL), '[]'::json) as sources,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'entity_id', ent.id,
                        'canonical_name', ent.canonical_name,
                        'entity_type', ent.entity_type,
                        'role', ee.role
                    )) FILTER (WHERE ent.id IS NOT NULL), '[]'::json) as entities
                FROM fiction_events e
                LEFT JOIN fiction_event_sources s ON e.id = s.event_id
                LEFT JOIN fiction_event_entities ee ON e.id = ee.event_id
                LEFT JOIN fiction_entities ent ON ee.entity_id = ent.id
                WHERE 1=1
            """
            params = []
            if topic:
                query += " AND %s = ANY(e.topics)"
                params.append(topic)
            if country:
                query += " AND e.country ILIKE %s"
                params.append(f"%{country}%")

            query += " GROUP BY e.id ORDER BY e.event_date DESC NULLS LAST, e.created_at DESC LIMIT %s OFFSET %s;"
            params.extend([limit, offset])

            cur.execute(query, tuple(params))
            return list(cur.fetchall())


@db_retry(max_retries=3, delay=1.0)
def get_event_by_id(event_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single event with complete provenance and entity relationships."""
    events = get_all_events(limit=1, offset=0)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    e.id, e.event_type, e.title, e.description, e.main_action,
                    e.event_date, e.date_precision, e.location, e.country, e.topics,
                    e.extraction_confidence, e.created_at,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'article_id', s.article_id,
                        'source_url', s.source_url,
                        'publisher', s.publisher,
                        'evidence_excerpt', s.evidence_excerpt,
                        'published_at', s.published_at
                    )) FILTER (WHERE s.id IS NOT NULL), '[]'::json) as sources,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'entity_id', ent.id,
                        'canonical_name', ent.canonical_name,
                        'entity_type', ent.entity_type,
                        'role', ee.role
                    )) FILTER (WHERE ent.id IS NOT NULL), '[]'::json) as entities
                FROM fiction_events e
                LEFT JOIN fiction_event_sources s ON e.id = s.event_id
                LEFT JOIN fiction_event_entities ee ON e.id = ee.event_id
                LEFT JOIN fiction_entities ent ON ee.entity_id = ent.id
                WHERE e.id = %s
                GROUP BY e.id;
            """, (event_id,))
            return cur.fetchone()


# =====================================================================
# Entities
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def get_or_create_entity(canonical_name: str, entity_type: str, aliases: List[str] = None, description: str = "") -> int:
    """Inserts or retrieves a canonical entity."""
    aliases = aliases or []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_entities (canonical_name, entity_type, aliases, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (canonical_name) DO UPDATE SET
                    aliases = ARRAY(SELECT DISTINCT unnest(fiction_entities.aliases || EXCLUDED.aliases)),
                    description = COALESCE(NULLIF(EXCLUDED.description, ''), fiction_entities.description)
                RETURNING id;
            """, (canonical_name, entity_type, aliases, description))
            entity_id = cur.fetchone()["id"]
            conn.commit()
            return entity_id


@db_retry(max_retries=3, delay=1.0)
def link_event_entity(event_id: int, entity_id: int, role: str = "PARTICIPANT"):
    """Associates an entity with an event under a specific participation role."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_event_entities (event_id, entity_id, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (event_id, entity_id, role) DO NOTHING;
            """, (event_id, entity_id, role))
            conn.commit()


# =====================================================================
# Relationships
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def insert_event_relation(
    source_event_id: int,
    target_event_id: int,
    relation_type: str,
    is_verified: bool = False,
    confidence: float = 0.5,
    evidence_text: str = "",
    shared_entity_id: Optional[int] = None
) -> int:
    """Records a directional relationship between two events."""
    if source_event_id == target_event_id:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_event_relations
                (source_event_id, target_event_id, relation_type, is_verified, confidence, evidence_text, shared_entity_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_event_id, target_event_id, relation_type) DO UPDATE SET
                    is_verified = EXCLUDED.is_verified,
                    confidence = EXCLUDED.confidence,
                    evidence_text = EXCLUDED.evidence_text
                RETURNING id;
            """, (source_event_id, target_event_id, relation_type, is_verified, confidence, evidence_text, shared_entity_id))
            row = cur.fetchone()
            conn.commit()
            return row["id"] if row else 0


@db_retry(max_retries=3, delay=1.0)
def get_event_relations(event_id: Optional[int] = None, limit: int = 200) -> List[Dict[str, Any]]:
    """Retrieves relations with source & target event metadata."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT 
                    r.id, r.source_event_id, r.target_event_id, r.relation_type,
                    r.is_verified, r.confidence, r.evidence_text,
                    se.title as source_title, se.event_type as source_type,
                    te.title as target_title, te.event_type as target_type,
                    ent.canonical_name as shared_entity_name
                FROM fiction_event_relations r
                JOIN fiction_events se ON r.source_event_id = se.id
                JOIN fiction_events te ON r.target_event_id = te.id
                LEFT JOIN fiction_entities ent ON r.shared_entity_id = ent.id
            """
            params = []
            if event_id:
                query += " WHERE r.source_event_id = %s OR r.target_event_id = %s"
                params.extend([event_id, event_id])
            query += " ORDER BY r.confidence DESC, r.created_at DESC LIMIT %s;"
            params.append(limit)

            cur.execute(query, tuple(params))
            return list(cur.fetchall())


# =====================================================================
# Clusters
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def insert_cluster(
    cluster_code: Any = None,
    name: Optional[str] = None,
    theme: Optional[str] = None,
    summary: Optional[str] = None,
    domains: Optional[List[str]] = None,
    event_ids: Optional[List[int]] = None,
    **kwargs
) -> int:
    """Inserts a multi-event narrative cluster. Supports dict record or explicit kwargs."""
    if isinstance(cluster_code, dict):
        d = cluster_code
        cluster_code = d.get("cluster_code") or f"CLUSTER-{uuid.uuid4().hex[:8].upper()}"
        name = d.get("name") or "Narrative Convergence"
        theme = d.get("theme") or "Cross-Domain Narrative"
        summary = d.get("summary") or ""
        domains = d.get("domains") or ["General"]
        event_ids = d.get("event_ids") or []

    if not cluster_code:
        cluster_code = f"CLUSTER-{uuid.uuid4().hex[:8].upper()}"
    name = name or "Narrative Convergence"
    theme = theme or "Cross-Domain Narrative"
    summary = summary or ""
    domains = domains or ["General"]
    event_ids = event_ids or []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_clusters (cluster_code, name, theme, summary, domains, event_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (cluster_code) DO UPDATE SET
                    name = EXCLUDED.name,
                    theme = EXCLUDED.theme,
                    summary = EXCLUDED.summary,
                    domains = EXCLUDED.domains,
                    event_count = EXCLUDED.event_count
                RETURNING id;
            """, (cluster_code, name, theme, summary, domains, len(event_ids)))
            cluster_id = cur.fetchone()["id"]

            for eid in event_ids:
                cur.execute("""
                    INSERT INTO fiction_cluster_events (cluster_id, event_id)
                    VALUES (%s, %s)
                    ON CONFLICT (cluster_id, event_id) DO NOTHING;
                """, (cluster_id, eid))
            conn.commit()
            return cluster_id


@db_retry(max_retries=3, delay=1.0)
def get_all_clusters(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Retrieves all event clusters with event details."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    c.id, c.cluster_code, c.name, c.theme, c.summary, c.domains, c.event_count, c.created_at,
                    COALESCE(json_agg(jsonb_build_object(
                        'id', e.id,
                        'title', e.title,
                        'event_type', e.event_type,
                        'event_date', e.event_date,
                        'country', e.country,
                        'topics', e.topics
                    )) FILTER (WHERE e.id IS NOT NULL), '[]'::json) as events
                FROM fiction_clusters c
                LEFT JOIN fiction_cluster_events ce ON c.id = ce.cluster_id
                LEFT JOIN fiction_events e ON ce.event_id = e.id
                GROUP BY c.id
                ORDER BY c.created_at DESC
                LIMIT %s OFFSET %s;
            """, (limit, offset))
            return list(cur.fetchall())


@db_retry(max_retries=3, delay=1.0)
def get_cluster_by_id(cluster_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a cluster with complete event metadata and connected scenarios."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    c.id, c.cluster_code, c.name, c.theme, c.summary, c.domains, c.event_count, c.created_at,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'id', e.id,
                        'title', e.title,
                        'event_type', e.event_type,
                        'description', e.description,
                        'event_date', e.event_date,
                        'country', e.country,
                        'location', e.location,
                        'topics', e.topics
                    )) FILTER (WHERE e.id IS NOT NULL), '[]'::json) as events,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'id', s.id,
                        'title', s.title,
                        'genre', s.genre,
                        'logline', s.logline,
                        'status', s.status,
                        'evaluation_scores', s.evaluation_scores
                    )) FILTER (WHERE s.id IS NOT NULL), '[]'::json) as scenarios
                FROM fiction_clusters c
                LEFT JOIN fiction_cluster_events ce ON c.id = ce.cluster_id
                LEFT JOIN fiction_events e ON ce.event_id = e.id
                LEFT JOIN fiction_scenarios s ON c.id = s.cluster_id
                WHERE c.id = %s
                GROUP BY c.id;
            """, (cluster_id,))
            return cur.fetchone()


# =====================================================================
# Scenarios
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def insert_scenario(
    cluster_id: int,
    title: str,
    genre: str,
    logline: str,
    premise: str,
    verified_facts: List[str],
    unverified_observations: List[str],
    fictional_assumptions: List[str],
    fictional_characters: List[Dict[str, str]],
    central_conflict: str,
    possible_antagonist: str,
    narrative_stakes: str,
    potential_twists: List[str],
    disclaimer: str,
    evaluation_scores: Dict[str, Any] = None,
    evaluation_feedback: str = "",
    status: str = "CANDIDATE"
) -> int:
    """Inserts a generated fictional hypothesis/scenario."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_scenarios
                (cluster_id, title, genre, logline, premise, verified_facts, unverified_observations,
                 fictional_assumptions, fictional_characters, central_conflict, possible_antagonist,
                 narrative_stakes, potential_twists, disclaimer, evaluation_scores, evaluation_feedback, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                cluster_id, title, genre, logline, premise,
                json.dumps(verified_facts), json.dumps(unverified_observations),
                json.dumps(fictional_assumptions), json.dumps(fictional_characters),
                central_conflict, possible_antagonist, narrative_stakes,
                potential_twists, disclaimer, json.dumps(evaluation_scores or {}),
                evaluation_feedback, status
            ))
            scenario_id = cur.fetchone()["id"]
            conn.commit()
            return scenario_id


@db_retry(max_retries=3, delay=1.0)
def get_all_scenarios(cluster_id: Optional[int] = None, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves scenarios with cluster metadata."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT 
                    s.id, s.cluster_id, s.title, s.genre, s.logline, s.premise,
                    s.verified_facts, s.unverified_observations, s.fictional_assumptions,
                    s.fictional_characters, s.central_conflict, s.possible_antagonist,
                    s.narrative_stakes, s.potential_twists, s.disclaimer,
                    s.evaluation_scores, s.evaluation_feedback, s.status, s.created_at,
                    c.name as cluster_name, c.theme as cluster_theme
                FROM fiction_scenarios s
                LEFT JOIN fiction_clusters c ON s.cluster_id = c.id
                WHERE 1=1
            """
            params = []
            if cluster_id:
                query += " AND s.cluster_id = %s"
                params.append(cluster_id)
            if status:
                query += " AND s.status = %s"
                params.append(status)
            query += " ORDER BY s.created_at DESC LIMIT %s;"
            params.append(limit)

            cur.execute(query, tuple(params))
            return list(cur.fetchall())


@db_retry(max_retries=3, delay=1.0)
def get_scenario_by_id(scenario_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single scenario by ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    s.id, s.cluster_id, s.title, s.genre, s.logline, s.premise,
                    s.verified_facts, s.unverified_observations, s.fictional_assumptions,
                    s.fictional_characters, s.central_conflict, s.possible_antagonist,
                    s.narrative_stakes, s.potential_twists, s.disclaimer,
                    s.evaluation_scores, s.evaluation_feedback, s.status, s.created_at,
                    c.name as cluster_name, c.theme as cluster_theme
                FROM fiction_scenarios s
                LEFT JOIN fiction_clusters c ON s.cluster_id = c.id
                WHERE s.id = %s;
            """, (scenario_id,))
            return cur.fetchone()


@db_retry(max_retries=3, delay=1.0)
def update_scenario_status(scenario_id: int, status: str):
    """Updates scenario status (e.g. SELECTED or REJECTED)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE fiction_scenarios SET status = %s WHERE id = %s;", (status, scenario_id))
            conn.commit()


# =====================================================================
# Stories & Chapters
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def insert_story(
    scenario_id: Optional[int],
    cluster_id: Optional[int],
    title: str,
    genre: str,
    synopsis: str,
    world_setting: str,
    central_conflict: str,
    ending_plan: str,
    disclaimer: str,
    status: str = "PLANNED"
) -> int:
    """Inserts a planned or generated story outline."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_stories
                (scenario_id, cluster_id, title, genre, synopsis, world_setting, central_conflict, ending_plan, disclaimer, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (scenario_id, cluster_id, title, genre, synopsis, world_setting, central_conflict, ending_plan, disclaimer, status))
            story_id = cur.fetchone()["id"]
            conn.commit()
            return story_id


@db_retry(max_retries=3, delay=1.0)
def insert_chapter(
    story_id: int,
    chapter_number: int,
    title: str,
    summary: str,
    content: str,
    word_count: int = 0,
    status: str = "DRAFT"
) -> int:
    """Inserts or updates an individual chapter."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_chapters
                (story_id, chapter_number, title, summary, content, word_count, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (story_id, chapter_number) DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    content = EXCLUDED.content,
                    word_count = EXCLUDED.word_count,
                    status = EXCLUDED.status,
                    updated_at = NOW()
                RETURNING id;
            """, (story_id, chapter_number, title, summary, content, word_count, status))
            chapter_id = cur.fetchone()["id"]
            conn.commit()
            return chapter_id


@db_retry(max_retries=3, delay=1.0)
def get_all_stories(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Retrieves all stories with chapter count and status."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    s.id, s.scenario_id, s.cluster_id, s.title, s.genre, s.synopsis,
                    s.status, s.reading_time_mins, s.created_at, s.updated_at,
                    COUNT(ch.id) as chapter_count,
                    COALESCE(SUM(ch.word_count), 0) as total_words
                FROM fiction_stories s
                LEFT JOIN fiction_chapters ch ON s.id = ch.story_id
                GROUP BY s.id
                ORDER BY s.created_at DESC
                LIMIT %s OFFSET %s;
            """, (limit, offset))
            return list(cur.fetchall())


@db_retry(max_retries=3, delay=1.0)
def get_story_by_id(story_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a story with chapters, characters, and source events."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    s.id, s.scenario_id, s.cluster_id, s.title, s.genre, s.synopsis,
                    s.world_setting, s.central_conflict, s.ending_plan, s.disclaimer,
                    s.status, s.reading_time_mins, s.created_at, s.updated_at,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'id', ch.id,
                        'chapter_number', ch.chapter_number,
                        'title', ch.title,
                        'summary', ch.summary,
                        'content', ch.content,
                        'word_count', ch.word_count,
                        'status', ch.status
                    )) FILTER (WHERE ch.id IS NOT NULL), '[]'::json) as chapters,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'id', c.id,
                        'name', c.name,
                        'role', c.role,
                        'description', c.description,
                        'motivations', c.motivations
                    )) FILTER (WHERE c.id IS NOT NULL), '[]'::json) as characters
                FROM fiction_stories s
                LEFT JOIN fiction_chapters ch ON s.id = ch.story_id
                LEFT JOIN fiction_characters c ON s.id = c.story_id
                WHERE s.id = %s
                GROUP BY s.id;
            """, (story_id,))
            return cur.fetchone()


@db_retry(max_retries=3, delay=1.0)
def get_chapter_by_id(chapter_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves an individual chapter."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, story_id, chapter_number, title, summary, content, word_count, status, created_at, updated_at
                FROM fiction_chapters
                WHERE id = %s;
            """, (chapter_id,))
            return cur.fetchone()


# =====================================================================
# Characters & Continuity
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def insert_character(story_id: int, name: str, role: str, description: str, motivations: str) -> int:
    """Inserts a character into a story's continuity registry."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_characters (story_id, name, role, description, motivations)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (story_id, name) DO UPDATE SET
                    role = EXCLUDED.role,
                    description = EXCLUDED.description,
                    motivations = EXCLUDED.motivations
                RETURNING id;
            """, (story_id, name, role, description, motivations))
            char_id = cur.fetchone()["id"]
            conn.commit()
            return char_id


@db_retry(max_retries=3, delay=1.0)
def insert_character_relationship(story_id: int, char_a_id: int, char_b_id: int, rel_type: str, description: str):
    """Inserts a relationship between two story characters."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_character_relationships (story_id, character_a_id, character_b_id, relationship_type, description)
                VALUES (%s, %s, %s, %s, %s);
            """, (story_id, char_a_id, char_b_id, rel_type, description))
            conn.commit()


@db_retry(max_retries=3, delay=1.0)
def get_story_continuity_state(story_id: int) -> Dict[str, Any]:
    """Retrieves the full persistent narrative memory for a story."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, role, description, motivations FROM fiction_characters WHERE story_id = %s;", (story_id,))
            chars = list(cur.fetchall())

            cur.execute("""
                SELECT r.id, r.relationship_type, r.description,
                       ca.name as character_a_name, cb.name as character_b_name
                FROM fiction_character_relationships r
                JOIN fiction_characters ca ON r.character_a_id = ca.id
                JOIN fiction_characters cb ON r.character_b_id = cb.id
                WHERE r.story_id = %s;
            """, (story_id,))
            rels = list(cur.fetchall())

            cur.execute("""
                SELECT chapter_number, title, summary 
                FROM fiction_chapters 
                WHERE story_id = %s 
                ORDER BY chapter_number ASC;
            """, (story_id,))
            chap_summaries = list(cur.fetchall())

            return {
                "story_id": story_id,
                "active_characters": chars,
                "character_relationships": rels,
                "previous_chapter_summaries": chap_summaries
            }


@db_retry(max_retries=3, delay=1.0)
def update_scenario_evaluation(scenario_id: int, scores: Dict[str, Any], feedback: str, is_approved: bool = True):
    """Updates scenario evaluation scores and status."""
    status = "CANDIDATE" if is_approved else "REJECTED"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE fiction_scenarios 
                SET evaluation_scores = %s, evaluation_feedback = %s, status = %s
                WHERE id = %s;
            """, (json.dumps(scores), feedback, status, scenario_id))
            conn.commit()


@db_retry(max_retries=3, delay=1.0)
def link_story_event(story_id: int, event_id: int, factual_elements: str = "", fictional_transformation: str = ""):
    """Links a real-world event to a story with transformation notes."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_story_event_links 
                (story_id, event_id, factual_elements_used, fictional_transformation)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (story_id, event_id) DO UPDATE SET
                    factual_elements_used = EXCLUDED.factual_elements_used,
                    fictional_transformation = EXCLUDED.fictional_transformation;
            """, (story_id, event_id, factual_elements, fictional_transformation))
            conn.commit()


@db_retry(max_retries=3, delay=1.0)
def update_story_stats(story_id: int, reading_time_mins: int = None, status: str = None):
    """Updates story reading time and/or status."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if reading_time_mins is not None and status is not None:
                cur.execute("UPDATE fiction_stories SET reading_time_mins = %s, status = %s, updated_at = NOW() WHERE id = %s;", (reading_time_mins, status, story_id))
            elif reading_time_mins is not None:
                cur.execute("UPDATE fiction_stories SET reading_time_mins = %s, updated_at = NOW() WHERE id = %s;", (reading_time_mins, story_id))
            elif status is not None:
                cur.execute("UPDATE fiction_stories SET status = %s, updated_at = NOW() WHERE id = %s;", (status, story_id))
            conn.commit()


# =====================================================================
# Job Tracking
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def create_job_run(job_type: str, current_stage: str = "INITIALIZING") -> int:
    """Creates a new tracked background job."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_job_runs (job_type, status, progress_pct, current_stage)
                VALUES (%s, 'RUNNING', 5, %s)
                RETURNING id;
            """, (job_type, current_stage))
            job_id = cur.fetchone()["id"]
            conn.commit()
            return job_id


@db_retry(max_retries=3, delay=1.0)
def update_job_run(
    job_id: int,
    status: str,
    progress_pct: int,
    current_stage: str = "PROCESSING",
    stage: Optional[str] = None,
    result_summary: Dict[str, Any] = None,
    error_message: Optional[str] = None
):
    """Updates background job progress or outcome."""
    effective_stage = stage or current_stage
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE fiction_job_runs
                SET status = %s,
                    progress_pct = %s,
                    current_stage = %s,
                    result_summary = COALESCE(%s, result_summary),
                    error_message = %s,
                    updated_at = NOW()
                WHERE id = %s;
            """, (status, progress_pct, effective_stage, json.dumps(result_summary) if result_summary else None, error_message, job_id))
            conn.commit()


@db_retry(max_retries=3, delay=1.0)
def get_job_run(job_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves status and results for a job run."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, job_type, status, progress_pct, current_stage, result_summary, error_message, created_at, updated_at
                FROM fiction_job_runs
                WHERE id = %s;
            """, (job_id,))
            return cur.fetchone()
