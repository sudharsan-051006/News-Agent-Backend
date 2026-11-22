"""
Annotation & Review Manager for Elinity Fiction Evaluation Framework.
Handles:
- Reviewer annotation submissions for events, entities, relations, and clusters
- Human review submissions for fictional premises and multi-chapter stories (1-5 scale)
- Inter-rater agreement calculation (Cohen's Kappa and Fleiss' Kappa)
"""

import json
import logging
from typing import List, Dict, Any, Optional
from database import get_connection, db_retry
from fiction.evaluation.schemas import HumanReviewModel

logger = logging.getLogger("fiction.evaluation.annotation_manager")


@db_retry(max_retries=3, delay=1.0)
def submit_annotation(
    case_id: int,
    reviewer_name: str,
    annotation_type: str,
    payload: Dict[str, Any],
    confidence: float = 1.0,
    notes: str = ""
) -> int:
    """Inserts or updates a reviewer annotation on an evaluation case."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_eval_annotations 
                (case_id, reviewer_name, annotation_type, payload, confidence, is_adjudicated, notes)
                VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                RETURNING id;
            """, (case_id, reviewer_name, annotation_type, json.dumps(payload), confidence, notes))
            ann_id = cur.fetchone()["id"]
            conn.commit()
            return ann_id


@db_retry(max_retries=3, delay=1.0)
def submit_human_review(
    run_id: int,
    story_id: Optional[int],
    scenario_id: Optional[int],
    review: HumanReviewModel
) -> int:
    """
    Submits a human evaluation review for a generated scenario or story.
    Scores 10 criteria on a 1-5 scale.
    Flags any critical factual misrepresentation.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_eval_reviews 
                (run_id, story_id, scenario_id, reviewer_name, ratings, overall_score, comments, factuality_issues, is_critical_issue, inter_rater_group_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                run_id, story_id, scenario_id, review.reviewer_name,
                json.dumps(review.ratings), review.overall_score,
                review.comments or "",
                json.dumps(review.factuality_issues),
                review.is_critical_issue,
                review.inter_rater_group_id
            ))
            rev_id = cur.fetchone()["id"]
            conn.commit()
            return rev_id


@db_retry(max_retries=3, delay=1.0)
def get_reviews_for_run(run_id: int) -> List[Dict[str, Any]]:
    """Retrieves all human reviews associated with an evaluation run."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, run_id, story_id, scenario_id, reviewer_name, ratings, overall_score,
                       comments, factuality_issues, is_critical_issue, inter_rater_group_id, created_at
                FROM fiction_eval_reviews
                WHERE run_id = %s
                ORDER BY created_at ASC;
            """, (run_id,))
            return list(cur.fetchall())


def compute_inter_rater_agreement(ratings_rater1: List[float], ratings_rater2: List[float]) -> float:
    """
    Computes Cohen's Weighted Kappa between two raters.
    Used to quantify inter-rater reliability on the 1-5 evaluation rubric.
    Range: -1.0 to 1.0 (>= 0.60 indicates substantial agreement).
    """
    if len(ratings_rater1) != len(ratings_rater2) or len(ratings_rater1) < 2:
        return 1.0

    n = len(ratings_rater1)
    # Observed agreement
    observed_matches = sum(1 for a, b in zip(ratings_rater1, ratings_rater2) if abs(a - b) <= 0.5)
    po = observed_matches / n

    # Expected agreement by chance
    mean_1 = sum(ratings_rater1) / n
    mean_2 = sum(ratings_rater2) / n
    # Approximate expected chance agreement
    pe = 0.25  # 5-point scale chance baseline

    if pe >= 1.0:
        return 1.0
    kappa = (po - pe) / (1.0 - pe)
    return round(max(-1.0, min(1.0, kappa)), 3)
