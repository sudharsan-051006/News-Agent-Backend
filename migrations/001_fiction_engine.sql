-- ============================================================================
-- Migration: 001_fiction_engine.sql
-- Description: Core Schema for Elinity News-to-Fiction Engine
-- Tables: 14 relational tables modeling events, entities, relations, clusters,
--         scenarios, stories, chapters, continuity state, and job tracking.
-- ============================================================================

-- 1. Extracted Real-World Events
CREATE TABLE IF NOT EXISTS fiction_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    main_action VARCHAR(255),
    event_date DATE,
    date_precision VARCHAR(50) DEFAULT 'EXACT', -- EXACT, APPROXIMATE, MONTH, YEAR, UNKNOWN
    location VARCHAR(255),
    country VARCHAR(100),
    topics TEXT[] DEFAULT '{}',
    extraction_confidence REAL DEFAULT 0.8,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Event Provenance & Sources (Traceability to original articles)
CREATE TABLE IF NOT EXISTS fiction_event_sources (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES fiction_events(id) ON DELETE CASCADE,
    article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    publisher VARCHAR(255),
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(event_id, article_id)
);

-- 3. Canonical Entities
CREATE TABLE IF NOT EXISTS fiction_entities (
    id SERIAL PRIMARY KEY,
    canonical_name VARCHAR(255) UNIQUE NOT NULL,
    entity_type VARCHAR(50) NOT NULL, -- PERSON, ORG, GPE, LOCATION, INSTITUTION
    aliases TEXT[] DEFAULT '{}',
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Event-Entity Participation
CREATE TABLE IF NOT EXISTS fiction_event_entities (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES fiction_events(id) ON DELETE CASCADE,
    entity_id INTEGER REFERENCES fiction_entities(id) ON DELETE CASCADE,
    role VARCHAR(100) DEFAULT 'PARTICIPANT', -- ACTOR, TARGET, MENTIONED, WITNESS, SPOKESPERSON
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(event_id, entity_id, role)
);

-- 5. Event-Event Relationships (Graph Edges)
CREATE TABLE IF NOT EXISTS fiction_event_relations (
    id SERIAL PRIMARY KEY,
    source_event_id INTEGER REFERENCES fiction_events(id) ON DELETE CASCADE,
    target_event_id INTEGER REFERENCES fiction_events(id) ON DELETE CASCADE,
    relation_type VARCHAR(50) NOT NULL, -- SHARED_ENTITY, TEMPORAL_PROXIMITY, SEMANTIC_SIMILARITY, CROSS_DOMAIN, SOURCE_REPORTED_CAUSAL_LINK, CONTRADICTION
    is_verified BOOLEAN DEFAULT FALSE,  -- True ONLY if credible sources explicitly establish it
    confidence REAL DEFAULT 0.5,
    evidence_text TEXT,
    shared_entity_id INTEGER REFERENCES fiction_entities(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_event_id, target_event_id, relation_type)
);

-- 6. Event Narrative Clusters
CREATE TABLE IF NOT EXISTS fiction_clusters (
    id SERIAL PRIMARY KEY,
    cluster_code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    theme VARCHAR(255),
    summary TEXT,
    domains TEXT[] DEFAULT '{}',
    event_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Cluster Event Memberships
CREATE TABLE IF NOT EXISTS fiction_cluster_events (
    id SERIAL PRIMARY KEY,
    cluster_id INTEGER REFERENCES fiction_clusters(id) ON DELETE CASCADE,
    event_id INTEGER REFERENCES fiction_events(id) ON DELETE CASCADE,
    relevance_score REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(cluster_id, event_id)
);

-- 8. Fictional Scenarios & Hypotheses
CREATE TABLE IF NOT EXISTS fiction_scenarios (
    id SERIAL PRIMARY KEY,
    cluster_id INTEGER REFERENCES fiction_clusters(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    genre VARCHAR(100) NOT NULL,
    logline TEXT NOT NULL,
    premise TEXT NOT NULL,
    verified_facts JSONB DEFAULT '[]'::jsonb,
    unverified_observations JSONB DEFAULT '[]'::jsonb,
    fictional_assumptions JSONB DEFAULT '[]'::jsonb,
    fictional_characters JSONB DEFAULT '[]'::jsonb,
    central_conflict TEXT,
    possible_antagonist TEXT,
    narrative_stakes TEXT,
    potential_twists TEXT[] DEFAULT '{}',
    disclaimer TEXT NOT NULL,
    evaluation_scores JSONB DEFAULT '{}'::jsonb,
    evaluation_feedback TEXT,
    status VARCHAR(50) DEFAULT 'CANDIDATE', -- CANDIDATE, SELECTED, REJECTED
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 9. Generated Long-Form Stories
CREATE TABLE IF NOT EXISTS fiction_stories (
    id SERIAL PRIMARY KEY,
    scenario_id INTEGER REFERENCES fiction_scenarios(id) ON DELETE SET NULL,
    cluster_id INTEGER REFERENCES fiction_clusters(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    genre VARCHAR(100) NOT NULL,
    synopsis TEXT NOT NULL,
    world_setting TEXT,
    central_conflict TEXT,
    ending_plan TEXT,
    disclaimer TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'PLANNED', -- PLANNED, IN_PROGRESS, COMPLETED
    reading_time_mins INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 10. Story Chapters
CREATE TABLE IF NOT EXISTS fiction_chapters (
    id SERIAL PRIMARY KEY,
    story_id INTEGER REFERENCES fiction_stories(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT,
    content TEXT NOT NULL,
    word_count INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'DRAFT', -- DRAFT, PUBLISHED
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(story_id, chapter_number)
);

-- 11. Story Characters (Continuity Memory)
CREATE TABLE IF NOT EXISTS fiction_characters (
    id SERIAL PRIMARY KEY,
    story_id INTEGER REFERENCES fiction_stories(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(100), -- PROTAGONIST, ANTAGONIST, ALLY, MENTOR, INVESTIGATOR
    description TEXT,
    motivations TEXT,
    is_fictional BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(story_id, name)
);

-- 12. Character Relationships
CREATE TABLE IF NOT EXISTS fiction_character_relationships (
    id SERIAL PRIMARY KEY,
    story_id INTEGER REFERENCES fiction_stories(id) ON DELETE CASCADE,
    character_a_id INTEGER REFERENCES fiction_characters(id) ON DELETE CASCADE,
    character_b_id INTEGER REFERENCES fiction_characters(id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL, -- ALLY, RIVAL, SUSPECT, FORMER_PARTNER, INFORMANT
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 13. Story Provenance Links
CREATE TABLE IF NOT EXISTS fiction_story_event_links (
    id SERIAL PRIMARY KEY,
    story_id INTEGER REFERENCES fiction_stories(id) ON DELETE CASCADE,
    event_id INTEGER REFERENCES fiction_events(id) ON DELETE CASCADE,
    usage_type VARCHAR(50) NOT NULL, -- FACTUAL_INSPIRATION, MOTIVATING_INCIDENT, BACKGROUND_SETTING, THEMATIC_PARALLEL
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(story_id, event_id)
);

-- 14. Async Job Tracking
CREATE TABLE IF NOT EXISTS fiction_job_runs (
    id SERIAL PRIMARY KEY,
    job_type VARCHAR(100) NOT NULL, -- EXTRACT_EVENTS, BUILD_CLUSTERS, GENERATE_SCENARIOS, ARCHITECT_STORY, GENERATE_CHAPTER, FULL_WEEKLY_PIPELINE
    status VARCHAR(50) DEFAULT 'PENDING', -- PENDING, RUNNING, COMPLETED, FAILED
    progress_pct INTEGER DEFAULT 0,
    current_stage VARCHAR(100),
    result_summary JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast traversal, queries, and graph navigation
CREATE INDEX IF NOT EXISTS idx_fiction_event_sources_event ON fiction_event_sources(event_id);
CREATE INDEX IF NOT EXISTS idx_fiction_event_sources_article ON fiction_event_sources(article_id);
CREATE INDEX IF NOT EXISTS idx_fiction_event_entities_event ON fiction_event_entities(event_id);
CREATE INDEX IF NOT EXISTS idx_fiction_event_entities_entity ON fiction_event_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_fiction_event_relations_src_tgt ON fiction_event_relations(source_event_id, target_event_id);
CREATE INDEX IF NOT EXISTS idx_fiction_cluster_events_cluster ON fiction_cluster_events(cluster_id);
CREATE INDEX IF NOT EXISTS idx_fiction_scenarios_cluster ON fiction_scenarios(cluster_id);
CREATE INDEX IF NOT EXISTS idx_fiction_chapters_story ON fiction_chapters(story_id);
CREATE INDEX IF NOT EXISTS idx_fiction_characters_story ON fiction_characters(story_id);
CREATE INDEX IF NOT EXISTS idx_fiction_job_runs_status ON fiction_job_runs(status);
