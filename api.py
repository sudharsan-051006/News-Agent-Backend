"""
FastAPI Backend Application for Elinity Platform & Fiction Engine.
Provides:
- Secure Trends API (eliminating direct frontend database queries)
- Fiction Engine REST API (Events, Clusters, Scenarios, Stories, Chapters, Continuity)
- Background Task Orchestration & Job Status Tracking
- Optional Supabase JWT Authentication / Bearer token validation
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import get_connection, db_retry
from fiction.db import (
    init_fiction_db,
    get_all_events,
    get_event_by_id,
    get_all_clusters,
    get_cluster_by_id,
    get_all_scenarios,
    get_scenario_by_id,
    get_all_stories,
    get_story_by_id,
    get_chapter_by_id,
    get_story_continuity_state,
    create_job_run,
    get_job_run,
    update_scenario_status
)
from fiction.pipeline import run_fiction_pipeline
from fiction.story_architect import architect_story
from fiction.chapter_writer import write_chapter, regenerate_single_chapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("elinity.api")

app = FastAPI(
    title="Elinity News & Fiction Engine API",
    version="1.0.0",
    description="Backend API powering real-time news trends and the News-to-Fiction Engine."
)

# Enable CORS for React frontend (Vite default: http://localhost:5173, etc.)
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
        init_fiction_db()
        logger.info("Fiction Engine database initialized.")
    except Exception as exc:
        logger.warning(f"DB startup check notice: {exc}")

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
    return {"status": "ok", "service": "Elinity News & Fiction Engine"}


# =====================================================================
# 1. Secure Trends Proxy API (Replaces frontend neonSql)
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


# =====================================================================
# 2. Fiction Events API
# =====================================================================

@app.get("/api/fiction/events")
def list_events(limit: int = Query(50, ge=1, le=100), offset: int = 0):
    """Retrieves extracted factual news events with provenance."""
    events = get_all_events(limit=limit, offset=offset)
    return {"count": len(events), "events": events}


@app.get("/api/fiction/events/{event_id}")
def get_event(event_id: int):
    """Retrieves single event details with linked entities and verbatim sources."""
    event = get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event


# =====================================================================
# 3. Fiction Clusters API
# =====================================================================

@app.get("/api/fiction/clusters")
def list_clusters(limit: int = Query(20, ge=1, le=50), offset: int = 0):
    """Retrieves narrative event clusters."""
    clusters = get_all_clusters(limit=limit, offset=offset)
    return {"count": len(clusters), "clusters": clusters}


@app.get("/api/fiction/clusters/{cluster_id}")
def get_cluster(cluster_id: int):
    """Retrieves cluster details including its constituent events and scenarios."""
    cluster = get_cluster_by_id(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    return cluster


# =====================================================================
# 4. Pipeline Execution & Job Status API
# =====================================================================

class GenerateRequest(BaseModel):
    days: int = 7
    max_clusters: int = 2
    auto_architect_story: bool = True


@app.post("/api/fiction/generate")
def trigger_generation(req: GenerateRequest, background_tasks: BackgroundTasks):
    """
    Triggers an asynchronous background execution of the News-to-Fiction pipeline.
    Returns the tracked job ID immediately.
    """
    job_id = create_job_run("ON_DEMAND_GENERATION", "QUEUED")

    def run_job(j_id: int, d: int, mc: int, auto_arch: bool):
        run_fiction_pipeline(days=d, max_clusters_to_process=mc, auto_architect_story=auto_arch, job_id=j_id)

    background_tasks.add_task(run_job, job_id, req.days, req.max_clusters, req.auto_architect_story)

    return {
        "job_id": job_id,
        "status": "QUEUED",
        "message": "Fiction Engine pipeline started in the background."
    }


@app.get("/api/fiction/jobs/{job_id}")
def get_job_status(job_id: int):
    """Retrieves status and progress of a background fiction generation job."""
    job = get_job_run(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


# =====================================================================
# 5. Fictional Scenarios API
# =====================================================================

@app.get("/api/fiction/scenarios")
def list_scenarios(
    cluster_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100)
):
    """Retrieves candidate and selected fictional scenarios."""
    scenarios = get_all_scenarios(cluster_id=cluster_id, status=status, limit=limit)
    return {"count": len(scenarios), "scenarios": scenarios}


@app.get("/api/fiction/scenarios/{scenario_id}")
def get_scenario(scenario_id: int):
    """Retrieves scenario details with full evaluation scores and fact/fiction breakdown."""
    scenario = get_scenario_by_id(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    return scenario


@app.post("/api/fiction/scenarios/{scenario_id}/select")
def select_scenario(scenario_id: int):
    """
    Selects a fictional scenario and automatically architects a full novel blueprint.
    Creates story record, character roster, relationship graph, and chapter plans.
    """
    scenario = get_scenario_by_id(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    try:
        story_res = architect_story(scenario_id)
        return {
            "message": "Scenario selected and story architected successfully.",
            "story": story_res
        }
    except Exception as exc:
        logger.error(f"Failed to architect story for scenario {scenario_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# =====================================================================
# 6. Stories & Chapters API
# =====================================================================

@app.get("/api/fiction/stories")
def list_stories(limit: int = Query(50, ge=1, le=100), offset: int = 0):
    """Retrieves all generated fiction stories."""
    stories = get_all_stories(limit=limit, offset=offset)
    return {"count": len(stories), "stories": stories}


@app.get("/api/fiction/stories/{story_id}")
def get_story(story_id: int):
    """
    Retrieves full story details with chapters, characters, and
    source news events for the mandatory Source Transparency Section.
    """
    story = get_story_by_id(story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found.")

    # Retrieve source events for transparency section
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    e.id as event_id,
                    e.title,
                    e.event_type,
                    e.description,
                    e.event_date,
                    e.country,
                    el.factual_elements_used,
                    el.fictional_transformation,
                    COALESCE(json_agg(DISTINCT jsonb_build_object(
                        'source_url', s.source_url,
                        'publisher', s.publisher,
                        'evidence_excerpt', s.evidence_excerpt
                    )) FILTER (WHERE s.id IS NOT NULL), '[]'::json) as sources
                FROM fiction_story_event_links el
                JOIN fiction_events e ON el.event_id = e.id
                LEFT JOIN fiction_event_sources s ON e.id = s.event_id
                WHERE el.story_id = %s
                GROUP BY e.id, el.factual_elements_used, el.fictional_transformation;
            """, (story_id,))
            source_events = list(cur.fetchall())

    story["source_events"] = source_events
    return story


class ChapterGenerateRequest(BaseModel):
    chapter_number: int


@app.post("/api/fiction/stories/{story_id}/chapters/generate")
def generate_chapter(story_id: int, req: ChapterGenerateRequest):
    """Generates prose for a specific planned chapter."""
    try:
        result = write_chapter(story_id=story_id, chapter_number=req.chapter_number)
        return result
    except Exception as exc:
        logger.error(f"Failed to generate chapter {req.chapter_number} for story {story_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/fiction/chapters/{chapter_id}/regenerate")
def regenerate_chapter(chapter_id: int):
    """Regenerates a single chapter with fresh prose while preserving continuity."""
    try:
        result = regenerate_single_chapter(chapter_id)
        return result
    except Exception as exc:
        logger.error(f"Failed to regenerate chapter {chapter_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/fiction/stories/{story_id}/continuity")
def get_continuity(story_id: int):
    """Retrieves full persistent narrative memory bible for the story."""
    state = get_story_continuity_state(story_id)
    return state


# =====================================================================
# 7. Evaluation & QA Framework Endpoints
# =====================================================================

from fiction.evaluation.dataset_manager import (
    create_dataset,
    get_all_datasets,
    get_dataset_by_id,
    get_cases_for_dataset,
    insert_eval_case,
    seed_pilot_dataset,
    export_dataset_json,
    import_dataset_json
)
from fiction.evaluation.annotation_manager import (
    submit_annotation,
    submit_human_review,
    get_reviews_for_run
)
from fiction.evaluation.evaluator import (
    execute_evaluation_run,
    get_eval_run_by_id,
    get_all_eval_runs
)
from fiction.evaluation.metric_aggregator import get_metrics_for_run
from fiction.evaluation.benchmark_runner import run_benchmark_suite
from fiction.evaluation.ablation_runner import run_full_ablation_suite
from fiction.evaluation.schemas import HumanReviewModel, EvalCaseModel


@app.get("/api/fiction/evaluation/datasets")
def list_datasets():
    """Retrieves all evaluation datasets in the registry."""
    datasets = get_all_datasets()
    return {"count": len(datasets), "datasets": datasets}


class CreateDatasetRequest(BaseModel):
    name: str
    version: str = "v1.0"
    description: str = ""
    domain: str = "General News"


@app.post("/api/fiction/evaluation/datasets")
def api_create_dataset(req: CreateDatasetRequest):
    """Creates a new evaluation dataset."""
    ds_id = create_dataset(req.name, req.version, req.description, req.domain)
    return {"dataset_id": ds_id, "message": "Evaluation dataset created."}


@app.get("/api/fiction/evaluation/datasets/{dataset_id}")
def api_get_dataset(dataset_id: int):
    """Retrieves dataset details and summary case count."""
    ds = get_dataset_by_id(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    cases = get_cases_for_dataset(dataset_id)
    ds["cases"] = cases
    return ds


@app.post("/api/fiction/evaluation/datasets/{dataset_id}/seed-pilot")
def api_seed_pilot(dataset_id: int):
    """Seeds the ground-truth pilot dataset."""
    seeded_id = seed_pilot_dataset()
    return {"message": "Pilot evaluation dataset seeded successfully.", "dataset_id": seeded_id}


@app.get("/api/fiction/evaluation/datasets/{dataset_id}/export")
def api_export_dataset(dataset_id: int):
    """Exports dataset to JSON."""
    json_str = export_dataset_json(dataset_id)
    return json.loads(json_str)


class AnnotationRequest(BaseModel):
    reviewer_name: str
    annotation_type: str  # 'EVENT', 'ENTITY', 'RELATION', 'CLUSTER'
    payload: Dict[str, Any]
    confidence: float = 1.0
    notes: str = ""


@app.post("/api/fiction/evaluation/datasets/{dataset_id}/cases/{case_id}/annotations")
def api_submit_annotation(dataset_id: int, case_id: int, req: AnnotationRequest):
    """Submits human review annotation for an evaluation case."""
    ann_id = submit_annotation(
        case_id=case_id,
        reviewer_name=req.reviewer_name,
        annotation_type=req.annotation_type,
        payload=req.payload,
        confidence=req.confidence,
        notes=req.notes
    )
    return {"annotation_id": ann_id, "message": "Annotation recorded successfully."}


class RunEvalRequest(BaseModel):
    dataset_id: Optional[int] = None
    run_type: str = "FULL"
    model_provider: str = "groq"
    model_name: str = "llama-3.3-70b-versatile"


@app.post("/api/fiction/evaluation/run")
def api_trigger_eval_run(req: RunEvalRequest, background_tasks: BackgroundTasks):
    """Triggers an asynchronous comprehensive evaluation run."""
    def run_task(d_id: Optional[int], r_type: str, m_prov: str, m_name: str):
        execute_evaluation_run(d_id, r_type, m_prov, m_name)

    # Initial seed check
    d_id = req.dataset_id or seed_pilot_dataset()
    background_tasks.add_task(run_task, d_id, req.run_type, req.model_provider, req.model_name)

    return {
        "status": "QUEUED",
        "dataset_id": d_id,
        "message": "Evaluation pipeline execution started in background."
    }


@app.get("/api/fiction/evaluation/runs")
def api_list_eval_runs(limit: int = Query(50, ge=1, le=100)):
    """Retrieves evaluation run history."""
    runs = get_all_eval_runs(limit=limit)
    return {"count": len(runs), "runs": runs}


@app.get("/api/fiction/evaluation/runs/{run_id}")
def api_get_eval_run(run_id: int):
    """Retrieves full evaluation run details."""
    run = get_eval_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return run


@app.get("/api/fiction/evaluation/runs/{run_id}/metrics")
def api_get_run_metrics(run_id: int):
    """Retrieves all component metrics and release gate targets for a run."""
    metrics = get_metrics_for_run(run_id)
    return {"run_id": run_id, "count": len(metrics), "metrics": metrics}


@app.get("/api/fiction/evaluation/runs/{run_id}/reports")
def api_get_run_reports(run_id: int):
    """Retrieves all generated report artifacts for an evaluation run."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, run_id, artifact_type, title, content, created_at
                FROM fiction_eval_artifacts
                WHERE run_id = %s
                ORDER BY created_at ASC;
            """, (run_id,))
            reports = list(cur.fetchall())
    return {"run_id": run_id, "count": len(reports), "reports": reports}


class BenchmarkRequest(BaseModel):
    run_id: int
    dataset_id: Optional[int] = None


@app.post("/api/fiction/evaluation/benchmark")
def api_run_benchmark(req: BenchmarkRequest, background_tasks: BackgroundTasks):
    """Triggers benchmark comparison across Baselines A, B, C, and D."""
    def run_bench(r_id: int, d_id: Optional[int]):
        run_benchmark_suite(r_id, d_id)

    background_tasks.add_task(run_bench, req.run_id, req.dataset_id)
    return {"status": "QUEUED", "message": "Baseline benchmark suite started in background."}


class AblationRequest(BaseModel):
    dataset_id: Optional[int] = None


@app.post("/api/fiction/evaluation/ablation")
def api_run_ablation(req: AblationRequest):
    """Runs full ablation suite and returns comparative performance deltas."""
    d_id = req.dataset_id or seed_pilot_dataset()
    cases = get_cases_for_dataset(d_id)
    ablation_results = run_full_ablation_suite(cases)
    return {"dataset_id": d_id, "results": ablation_results}


@app.get("/api/fiction/evaluation/comparisons")
def api_get_comparisons(run_id: Optional[int] = None):
    """Retrieves benchmark comparisons from PostgreSQL."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if run_id:
                cur.execute("""
                    SELECT id, run_id, comparison_type, system_variant, metrics, cost_tokens, execution_time_seconds, created_at
                    FROM fiction_eval_comparisons
                    WHERE run_id = %s
                    ORDER BY created_at ASC;
                """, (run_id,))
            else:
                cur.execute("""
                    SELECT id, run_id, comparison_type, system_variant, metrics, cost_tokens, execution_time_seconds, created_at
                    FROM fiction_eval_comparisons
                    ORDER BY created_at DESC
                    LIMIT 50;
                """)
            return {"comparisons": list(cur.fetchall())}


class HumanReviewSubmission(BaseModel):
    run_id: int
    story_id: Optional[int] = None
    scenario_id: Optional[int] = None
    review: HumanReviewModel


@app.post("/api/fiction/evaluation/reviews")
def api_submit_review(req: HumanReviewSubmission):
    """Submits human review for a story on 1-5 scale."""
    rev_id = submit_human_review(
        run_id=req.run_id,
        story_id=req.story_id,
        scenario_id=req.scenario_id,
        review=req.review
    )
    return {"review_id": rev_id, "message": "Human review recorded successfully."}


@app.get("/api/fiction/evaluation/reviews")
def api_get_reviews(run_id: Optional[int] = None):
    """Retrieves human reviews."""
    if not run_id:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, run_id, story_id, scenario_id, reviewer_name, ratings, overall_score,
                           comments, factuality_issues, is_critical_issue, created_at
                    FROM fiction_eval_reviews
                    ORDER BY created_at DESC
                    LIMIT 50;
                """)
                return {"reviews": list(cur.fetchall())}
    reviews = get_reviews_for_run(run_id)
    return {"run_id": run_id, "count": len(reviews), "reviews": reviews}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
