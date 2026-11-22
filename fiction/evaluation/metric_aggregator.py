"""
Metric Aggregator & Release Gate Auditor for Elinity Fiction Evaluation Framework.
Persists component metrics to PostgreSQL (fiction_eval_metrics) and audits against
Initial Engineering Acceptance Targets:
- Event extraction F1 >= 0.85
- Entity resolution accuracy >= 0.90
- Relationship Precision@5 >= 0.80
- Clustering B-cubed F1 >= 0.75
- Average story quality >= 4.0/5.0
- Fiction transparency >= 4.5/5.0
- Continuity consistency >= 0.90
- Critical factual misrepresentations == 0 (CRITICAL RELEASE GATE)
"""

import json
import logging
from typing import Dict, Any, List
from database import get_connection, db_retry

logger = logging.getLogger("fiction.evaluation.metric_aggregator")

ACCEPTANCE_TARGETS = {
    ("EVENT_EXTRACTION", "f1"): 0.85,
    ("ENTITY_RESOLUTION", "entity_linking_accuracy"): 0.90,
    ("RELATIONSHIP_DISCOVERY", "precision_at_k"): 0.80,
    ("CLUSTERING", "bcubed_f1"): 0.75,
    ("STORY_QUALITY", "overall_score"): 4.0,
    ("STORY_QUALITY", "fiction_transparency"): 4.5,
    ("CONTINUITY", "continuity_consistency_score"): 0.90,
    ("FACTUALITY_SAFETY", "critical_factual_misrepresentations"): 0.0,  # Max allowable is 0
}


@db_retry(max_retries=3, delay=1.0)
def save_metric(
    run_id: int,
    component: str,
    metric_name: str,
    metric_value: float,
    sample_size: int = 0,
    details: Dict[str, Any] = None
):
    """Persists a single metric record into PostgreSQL."""
    target = ACCEPTANCE_TARGETS.get((component, metric_name))
    is_passed = True
    if target is not None:
        if metric_name == "critical_factual_misrepresentations":
            is_passed = (metric_value <= target)
        else:
            is_passed = (metric_value >= target)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_eval_metrics
                (run_id, component, metric_name, metric_value, target_value, is_passed, sample_size, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, component, metric_name) DO UPDATE SET
                    metric_value = EXCLUDED.metric_value,
                    target_value = EXCLUDED.target_value,
                    is_passed = EXCLUDED.is_passed,
                    sample_size = EXCLUDED.sample_size,
                    details = EXCLUDED.details;
            """, (run_id, component, metric_name, metric_value, target, is_passed, sample_size, json.dumps(details or {})))
            conn.commit()


@db_retry(max_retries=3, delay=1.0)
def get_metrics_for_run(run_id: int) -> List[Dict[str, Any]]:
    """Retrieves all persisted metrics for an evaluation run."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, run_id, component, metric_name, metric_value, target_value, is_passed, sample_size, details, created_at
                FROM fiction_eval_metrics
                WHERE run_id = %s
                ORDER BY component, metric_name;
            """, (run_id,))
            return list(cur.fetchall())


def audit_release_gate(metrics_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Audits the complete evaluation run against release gate requirements.
    CRITICAL: Any critical factual misrepresentation automatically fails the release gate!
    """
    failed_criteria = []
    has_critical_safety_failure = False

    for m in metrics_list:
        comp = m.get("component")
        name = m.get("metric_name")
        val = m.get("metric_value", 0.0)
        target = m.get("target_value")

        if target is not None:
            if name == "critical_factual_misrepresentations":
                if val > 0:
                    has_critical_safety_failure = True
                    failed_criteria.append(f"Critical Safety Violation: {int(val)} defamatory or ungrounded factual claim(s) detected.")
            else:
                if val < target:
                    failed_criteria.append(f"{comp}.{name} scored {val:.2f} (Target >= {target:.2f})")

    gate_passed = (not has_critical_safety_failure and len(failed_criteria) == 0)

    return {
        "release_gate_passed": gate_passed,
        "has_critical_safety_failure": has_critical_safety_failure,
        "failed_criteria": failed_criteria,
        "total_metrics_evaluated": len(metrics_list)
    }
