-- Migration 002: Elinity Fiction Engine Evaluation, Benchmarking & QA Framework
-- Relational tables for datasets, ground-truth annotations, evaluation runs, metrics, human reviews, comparisons, and artifacts.

-- 1. Evaluation Datasets Catalog
CREATE TABLE IF NOT EXISTS fiction_eval_datasets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL DEFAULT 'v1.0',
    description TEXT,
    domain VARCHAR(100) DEFAULT 'General News',
    article_count INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, version)
);

-- 2. Evaluation Cases (Articles & Ground Truth)
CREATE TABLE IF NOT EXISTS fiction_eval_cases (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES fiction_eval_datasets(id) ON DELETE CASCADE,
    article_id INTEGER,
    article_url TEXT,
    article_title TEXT NOT NULL,
    article_content TEXT NOT NULL,
    publisher VARCHAR(150),
    published_at TIMESTAMPTZ,
    ground_truth_events JSONB DEFAULT '[]'::jsonb,
    ground_truth_entities JSONB DEFAULT '[]'::jsonb,
    ground_truth_relations JSONB DEFAULT '[]'::jsonb,
    ground_truth_cluster_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Human & Ground-Truth Annotations
CREATE TABLE IF NOT EXISTS fiction_eval_annotations (
    id SERIAL PRIMARY KEY,
    case_id INTEGER REFERENCES fiction_eval_cases(id) ON DELETE CASCADE,
    reviewer_name VARCHAR(150) NOT NULL,
    annotation_type VARCHAR(50) NOT NULL, -- 'EVENT', 'ENTITY', 'RELATION', 'CLUSTER'
    payload JSONB NOT NULL,
    confidence REAL DEFAULT 1.0, -- 0.0 to 1.0
    is_adjudicated BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Evaluation Runs (Full, Benchmark, Ablation, Component)
CREATE TABLE IF NOT EXISTS fiction_eval_runs (
    id SERIAL PRIMARY KEY,
    run_code VARCHAR(100) UNIQUE NOT NULL,
    dataset_id INTEGER REFERENCES fiction_eval_datasets(id) ON DELETE SET NULL,
    run_type VARCHAR(50) NOT NULL DEFAULT 'FULL', -- 'FULL', 'BENCHMARK', 'ABLATION', 'COMPONENT'
    pipeline_config JSONB DEFAULT '{}'::jsonb,
    model_provider VARCHAR(100) DEFAULT 'groq',
    model_name VARCHAR(150) DEFAULT 'llama-3.3-70b-versatile',
    prompt_version VARCHAR(50) DEFAULT 'v1.0',
    status VARCHAR(50) DEFAULT 'PENDING', -- 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED'
    current_stage VARCHAR(100) DEFAULT 'INITIALIZING',
    progress_pct INTEGER DEFAULT 0,
    error_message TEXT,
    release_gate_passed BOOLEAN DEFAULT FALSE,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 5. Evaluation Metrics & Detailed Component Scores
CREATE TABLE IF NOT EXISTS fiction_eval_metrics (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES fiction_eval_runs(id) ON DELETE CASCADE,
    component VARCHAR(100) NOT NULL, -- 'EVENT_EXTRACTION', 'ENTITY_RESOLUTION', 'RELATIONSHIP_DISCOVERY', 'CLUSTERING', 'SCENARIO', 'STORY_QUALITY', 'CONTINUITY', 'FACTUALITY_SAFETY', 'PERFORMANCE'
    metric_name VARCHAR(100) NOT NULL,
    metric_value REAL NOT NULL,
    target_value REAL,
    is_passed BOOLEAN DEFAULT TRUE,
    sample_size INTEGER DEFAULT 0,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id, component, metric_name)
);

-- 6. Human Review & Inter-Rater Evaluations
CREATE TABLE IF NOT EXISTS fiction_eval_reviews (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES fiction_eval_runs(id) ON DELETE CASCADE,
    story_id INTEGER,
    scenario_id INTEGER,
    reviewer_name VARCHAR(150) NOT NULL,
    ratings JSONB NOT NULL, -- 1-5 scale scores for news_grounding, connection_quality, creativity, coherence, readability, engagement, character_quality, pacing, continuity, fiction_transparency
    overall_score REAL NOT NULL,
    comments TEXT,
    factuality_issues JSONB DEFAULT '[]'::jsonb,
    is_critical_issue BOOLEAN DEFAULT FALSE,
    inter_rater_group_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Benchmark & Ablation Comparisons
CREATE TABLE IF NOT EXISTS fiction_eval_comparisons (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES fiction_eval_runs(id) ON DELETE CASCADE,
    comparison_type VARCHAR(50) NOT NULL, -- 'BASELINE', 'ABLATION'
    system_variant VARCHAR(100) NOT NULL, -- 'BASELINE_A_DIRECT_LLM', 'BASELINE_B_SEMANTIC', 'BASELINE_C_STRUCTURED', 'BASELINE_D_FULL_ELINITY', 'NO_ENTITY_RES', 'NO_RELATIONS', etc.
    metrics JSONB NOT NULL,
    cost_tokens INTEGER DEFAULT 0,
    execution_time_seconds REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id, system_variant)
);

-- 8. Evaluation Artifacts (JSON, Markdown, CSV Reports)
CREATE TABLE IF NOT EXISTS fiction_eval_artifacts (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES fiction_eval_runs(id) ON DELETE CASCADE,
    artifact_type VARCHAR(50) NOT NULL, -- 'REPORT_JSON', 'REPORT_MARKDOWN', 'REPORT_CSV', 'ERROR_LOG'
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_eval_cases_dataset ON fiction_eval_cases(dataset_id);
CREATE INDEX IF NOT EXISTS idx_eval_annotations_case ON fiction_eval_annotations(case_id);
CREATE INDEX IF NOT EXISTS idx_eval_runs_status ON fiction_eval_runs(status);
CREATE INDEX IF NOT EXISTS idx_eval_metrics_run ON fiction_eval_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_reviews_run ON fiction_eval_reviews(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_comparisons_run ON fiction_eval_comparisons(run_id);
