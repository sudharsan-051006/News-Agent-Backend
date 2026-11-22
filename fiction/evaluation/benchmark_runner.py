"""
Benchmark Runner for Elinity Fiction Evaluation Framework.
Coordinates reproducible benchmark runs across Baselines A, B, C, and D.
Stores comparative performance metrics in fiction_eval_comparisons.
"""

import json
import logging
from typing import List, Dict, Any
from database import get_connection, db_retry
from fiction.evaluation.dataset_manager import get_cases_for_dataset, seed_pilot_dataset
from fiction.evaluation.baseline_runner import (
    run_baseline_a_direct,
    run_baseline_b_semantic,
    run_baseline_c_structured,
    run_baseline_d_full
)

logger = logging.getLogger("fiction.evaluation.benchmark_runner")


@db_retry(max_retries=3, delay=1.0)
def save_comparison_result(
    run_id: int,
    comparison_type: str,
    system_variant: str,
    metrics: Dict[str, Any],
    cost_tokens: int,
    execution_time: float
):
    """Persists benchmark comparison record to PostgreSQL."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_eval_comparisons 
                (run_id, comparison_type, system_variant, metrics, cost_tokens, execution_time_seconds)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, system_variant) DO UPDATE SET
                    metrics = EXCLUDED.metrics,
                    cost_tokens = EXCLUDED.cost_tokens,
                    execution_time_seconds = EXCLUDED.execution_time_seconds
                RETURNING id;
            """, (run_id, comparison_type, system_variant, json.dumps(metrics), cost_tokens, execution_time))
            conn.commit()


def run_benchmark_suite(run_id: int, dataset_id: int = None) -> List[Dict[str, Any]]:
    """
    Executes all 4 baselines (A, B, C, D) on the dataset and records comparative findings.
    """
    if not dataset_id:
        dataset_id = seed_pilot_dataset()

    cases = get_cases_for_dataset(dataset_id)
    if not cases:
        logger.warning(f"No cases found in dataset {dataset_id}. Seeding pilot...")
        seed_pilot_dataset()
        cases = get_cases_for_dataset(dataset_id)

    results = []

    # 1. Baseline A: Direct LLM Generation
    logger.info("Executing Baseline A (Direct LLM Generation)...")
    res_a = run_baseline_a_direct(cases)
    save_comparison_result(
        run_id=run_id,
        comparison_type="BASELINE",
        system_variant=res_a["variant"],
        metrics=res_a,
        cost_tokens=res_a["total_tokens"],
        execution_time=res_a["execution_time_seconds"]
    )
    results.append(res_a)

    # 2. Baseline B: Semantic Similarity
    logger.info("Executing Baseline B (Semantic Similarity Grouping)...")
    res_b = run_baseline_b_semantic(cases)
    save_comparison_result(
        run_id=run_id,
        comparison_type="BASELINE",
        system_variant=res_b["variant"],
        metrics=res_b,
        cost_tokens=res_b["total_tokens"],
        execution_time=res_b["execution_time_seconds"]
    )
    results.append(res_b)

    # 3. Baseline C: Structured Event Pipeline
    logger.info("Executing Baseline C (Structured Event Pipeline)...")
    res_c = run_baseline_c_structured(cases)
    save_comparison_result(
        run_id=run_id,
        comparison_type="BASELINE",
        system_variant=res_c["variant"],
        metrics=res_c,
        cost_tokens=res_c["total_tokens"],
        execution_time=res_c["execution_time_seconds"]
    )
    results.append(res_c)

    # 4. Baseline D: Complete Elinity Pipeline
    logger.info("Executing Baseline D (Complete Elinity Pipeline)...")
    res_d = run_baseline_d_full(cases)
    save_comparison_result(
        run_id=run_id,
        comparison_type="BASELINE",
        system_variant=res_d["variant"],
        metrics=res_d,
        cost_tokens=res_d["total_tokens"],
        execution_time=res_d["execution_time_seconds"]
    )
    results.append(res_d)

    return results
