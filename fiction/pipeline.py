"""
Fiction Pipeline Orchestrator for Elinity Fiction Engine.
Coordinates the end-to-end autonomous transformation of real news into fictional narratives:
1. Ingest eligible articles from Neon DB
2. Extract structured real-world events with source provenance
3. Resolve entities and establish event-entity links
4. Discover and verify pairwise event relationships
5. Form narrative clusters (3 to 6 connected events)
6. Generate 5 distinct fictional premises across varied genres
7. Evaluate scenarios against 7 criteria (strict fact-fiction separation)
8. Architect complete novel outlines and generate initial chapters
9. Persist progress in fiction_job_runs
"""

import logging
import traceback
from typing import Dict, Any, Optional
from fiction.db import (
    init_fiction_db,
    get_eligible_articles,
    get_all_scenarios,
    create_job_run,
    update_job_run
)
from fiction.event_extractor import batch_extract_events
from fiction.connection_discovery import discover_event_relationships
from fiction.cluster_builder import build_event_clusters
from fiction.hypothesis_generator import generate_scenarios_for_cluster
from fiction.scenario_evaluator import evaluate_scenario
from fiction.story_architect import architect_story
from fiction.chapter_writer import write_chapter

logger = logging.getLogger("fiction.pipeline")


def run_fiction_pipeline(
    days: int = 7,
    max_clusters_to_process: int = 2,
    auto_architect_story: bool = True,
    job_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Executes the complete News-to-Fiction pipeline.
    Tracks execution status in PostgreSQL fiction_job_runs.
    """
    if not job_id:
        job_id = create_job_run("WEEKLY_FICTION_BATCH", "INITIALIZING")

    summary = {
        "job_id": job_id,
        "articles_processed": 0,
        "events_created": 0,
        "relations_created": 0,
        "clusters_created": 0,
        "scenarios_generated": 0,
        "scenarios_evaluated": 0,
        "stories_created": 0,
        "chapters_written": 0
    }

    try:
        # Step 0: Ensure DB tables exist
        update_job_run(job_id, status="RUNNING", progress_pct=5, stage="DB_INIT")
        init_fiction_db()

        # Step 1: Article Ingestion
        update_job_run(job_id, status="RUNNING", progress_pct=10, stage="FETCHING_ARTICLES")
        articles = get_eligible_articles(days=days, min_words=30, limit=100)
        logger.info(f"Retrieved {len(articles)} eligible articles for fiction extraction.")
        summary["articles_processed"] = len(articles)

        # Step 2: Event Extraction
        update_job_run(job_id, status="RUNNING", progress_pct=25, stage="EXTRACTING_EVENTS")
        if articles:
            ext_result = batch_extract_events(articles[:25])  # Process top 25 high-information articles
            summary["events_created"] = ext_result.get("events_created", 0)

        # Step 3: Relationship Discovery
        update_job_run(job_id, status="RUNNING", progress_pct=45, stage="DISCOVERING_RELATIONSHIPS")
        relations_count = discover_event_relationships(max_pairs=100)
        summary["relations_created"] = relations_count

        # Step 4: Narrative Clustering
        update_job_run(job_id, status="RUNNING", progress_pct=60, stage="CLUSTERING_EVENTS")
        clusters = build_event_clusters(min_events=3, max_events=6, max_clusters=max_clusters_to_process)
        summary["clusters_created"] = len(clusters)
        logger.info(f"Built {len(clusters)} narrative event clusters.")

        # Step 5 & 6: Hypothesis Generation & Evaluation
        update_job_run(job_id, status="RUNNING", progress_pct=75, stage="GENERATING_SCENARIOS")
        all_new_scenarios = []
        for cluster in clusters:
            c_scenarios = generate_scenarios_for_cluster(cluster["id"])
            all_new_scenarios.extend(c_scenarios)
            summary["scenarios_generated"] += len(c_scenarios)

        # Evaluate each scenario
        update_job_run(job_id, status="RUNNING", progress_pct=85, stage="EVALUATING_SCENARIOS")
        evaluated_scenarios = []
        for sc in all_new_scenarios:
            ev_res = evaluate_scenario(sc["id"])
            evaluated_scenarios.append(ev_res)
            summary["scenarios_evaluated"] += 1

        # Step 7: Story Architecture & Chapter 1 Prose
        if auto_architect_story and evaluated_scenarios:
            update_job_run(job_id, status="RUNNING", progress_pct=90, stage="ARCHITECTING_STORY")
            # Select highest scoring approved scenario
            approved = [e for e in evaluated_scenarios if e.get("is_approved")]
            if approved:
                best = max(approved, key=lambda x: x.get("scores", {}).get("total_score", 0))
            else:
                best = evaluated_scenarios[0]

            selected_sc_id = best["scenario_id"]
            story_res = architect_story(selected_sc_id)
            summary["stories_created"] += 1

            # Generate Chapter 1
            update_job_run(job_id, status="RUNNING", progress_pct=95, stage="WRITING_CHAPTER_ONE")
            story_id = story_res["story_id"]
            ch1_res = write_chapter(story_id=story_id, chapter_number=1)
            summary["chapters_written"] += 1
            summary["featured_story_id"] = story_id
            summary["featured_story_title"] = story_res.get("title")

        # Step 8: Complete Job
        update_job_run(
            job_id,
            status="COMPLETED",
            progress_pct=100,
            stage="FINISHED",
            result_summary=summary
        )
        logger.info(f"Fiction Pipeline Job {job_id} completed successfully. Summary: {summary}")
        return summary

    except Exception as exc:
        err_msg = f"{str(exc)}\n{traceback.format_exc()}"
        logger.error(f"Fiction Pipeline Job {job_id} failed: {err_msg}")
        update_job_run(
            job_id,
            status="FAILED",
            progress_pct=100,
            stage="FAILED",
            error_message=err_msg[:500]
        )
        summary["error"] = str(exc)
        return summary
