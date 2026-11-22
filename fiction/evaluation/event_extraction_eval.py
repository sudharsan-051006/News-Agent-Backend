"""
Event Extraction Evaluator for Elinity Fiction Evaluation Framework.
Measures:
- Precision, Recall, F1
- Event type accuracy
- Date extraction accuracy
- Entity extraction accuracy
- Evidence passage citation accuracy
- Detailed error breakdown (missing, false positives, date/entity mismatches)
Uses normalized semantic/token overlap matching rather than exact string equality.
"""

import re
import logging
from typing import List, Dict, Any, Tuple
from fiction.evaluation.schemas import EventExtractionMetrics

logger = logging.getLogger("fiction.evaluation.event_extraction")


def _tokenize(text: str) -> set:
    """Normalizes text into lowercased token set."""
    if not text:
        return set()
    return set(re.findall(r"\b[a-z0-9]+\b", text.lower()))


def _compute_token_jaccard(text_a: str, text_b: str) -> float:
    """Computes Jaccard similarity between two texts."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def evaluate_event_extraction(
    predicted_events: List[Dict[str, Any]],
    ground_truth_events: List[Dict[str, Any]],
    article_text: str = "",
    match_threshold: float = 0.35
) -> EventExtractionMetrics:
    """
    Evaluates predicted extracted events against ground truth for an article or batch.
    Matches predicted to ground truth using greedy bipartite matching over token similarity.
    """
    total_pred = len(predicted_events)
    total_gt = len(ground_truth_events)

    if total_gt == 0 and total_pred == 0:
        return EventExtractionMetrics(
            precision=1.0, recall=1.0, f1=1.0,
            type_accuracy=1.0, date_accuracy=1.0, entity_accuracy=1.0, evidence_accuracy=1.0,
            matched_events_count=0, total_predicted=0, total_ground_truth=0
        )

    if total_gt == 0:
        return EventExtractionMetrics(
            precision=0.0, recall=1.0, f1=0.0,
            type_accuracy=0.0, date_accuracy=0.0, entity_accuracy=0.0, evidence_accuracy=0.0,
            matched_events_count=0, total_predicted=total_pred, total_ground_truth=0,
            error_breakdown={"false_positives": [p.get("title", "") for p in predicted_events]}
        )

    if total_pred == 0:
        return EventExtractionMetrics(
            precision=1.0, recall=0.0, f1=0.0,
            type_accuracy=0.0, date_accuracy=0.0, entity_accuracy=0.0, evidence_accuracy=0.0,
            matched_events_count=0, total_predicted=0, total_ground_truth=total_gt,
            error_breakdown={"missing_events": [g.get("description", "") for g in ground_truth_events]}
        )

    # Compute similarity matrix
    matches = []
    used_pred = set()
    used_gt = set()

    # Pre-sort candidate pairs by Jaccard similarity DESC
    candidate_pairs = []
    for p_idx, p in enumerate(predicted_events):
        p_text = f"{p.get('title', '')} {p.get('description', '')} {p.get('main_action', '')}"
        for g_idx, g in enumerate(ground_truth_events):
            g_text = f"{g.get('description', '')} {' '.join(g.get('actions', []))}"
            sim = _compute_token_jaccard(p_text, g_text)
            if sim >= match_threshold:
                candidate_pairs.append((sim, p_idx, g_idx))

    candidate_pairs.sort(reverse=True, key=lambda x: x[0])

    for sim, p_idx, g_idx in candidate_pairs:
        if p_idx not in used_pred and g_idx not in used_gt:
            used_pred.add(p_idx)
            used_gt.add(g_idx)
            matches.append((sim, predicted_events[p_idx], ground_truth_events[g_idx]))

    matched_count = len(matches)
    precision = matched_count / total_pred if total_pred > 0 else 0.0
    recall = matched_count / total_gt if total_gt > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Secondary field metrics among matched events
    type_matches = 0
    date_matches = 0
    entity_overlap_scores = []
    evidence_valid_count = 0

    error_breakdown = {
        "missing_events": [],
        "false_positives": [],
        "date_mismatches": [],
        "entity_mismatches": [],
        "unsupported_evidence": []
    }

    for sim, pred, gt in matches:
        # 1. Type Match
        pred_type = str(pred.get("event_type", "")).upper().replace(" ", "_")
        gt_type = str(gt.get("event_type", "")).upper().replace(" ", "_")
        if pred_type == gt_type or pred_type in gt_type or gt_type in pred_type:
            type_matches += 1

        # 2. Date Match
        pred_date = str(pred.get("event_date", ""))
        gt_date = str(gt.get("event_date", ""))
        if pred_date and gt_date and (pred_date == gt_date or pred_date[:7] == gt_date[:7]):
            date_matches += 1
        elif gt_date and pred_date != gt_date:
            error_breakdown["date_mismatches"].append({
                "event": pred.get("title"),
                "predicted": pred_date,
                "ground_truth": gt_date
            })

        # 3. Entity Overlap
        def _extract_entity_strings(items):
            res = []
            for item in items:
                if isinstance(item, dict):
                    res.append(str(item.get("name") or item.get("canonical_name") or ""))
                else:
                    res.append(str(item))
            return res

        pred_ents = set(re.findall(r"\b[a-z0-9]+\b", " ".join(_extract_entity_strings(pred.get("participants", []) + pred.get("organizations", []))).lower()))
        gt_ents = set(re.findall(r"\b[a-z0-9]+\b", " ".join(_extract_entity_strings(gt.get("participants", []) + gt.get("entities", []))).lower()))
        if gt_ents:
            ent_jaccard = len(pred_ents & gt_ents) / len(pred_ents | gt_ents) if (pred_ents | gt_ents) else 0.0
            entity_overlap_scores.append(ent_jaccard)
            if ent_jaccard < 0.2:
                error_breakdown["entity_mismatches"].append({
                    "event": pred.get("title"),
                    "pred_entities": list(pred_ents)[:5],
                    "gt_entities": list(gt_ents)[:5]
                })
        else:
            entity_overlap_scores.append(1.0)

        # 4. Evidence Passage Verbatim Accuracy
        pred_evidence = pred.get("evidence_excerpts", [])
        if article_text and pred_evidence:
            valid_passages = sum(1 for exc in pred_evidence if exc and exc.strip() in article_text)
            if valid_passages > 0:
                evidence_valid_count += 1
            else:
                error_breakdown["unsupported_evidence"].append({
                    "event": pred.get("title"),
                    "excerpts": pred_evidence
                })
        else:
            evidence_valid_count += 1

    # Record unmatched errors
    for idx, g in enumerate(ground_truth_events):
        if idx not in used_gt:
            error_breakdown["missing_events"].append(g.get("description", ""))

    for idx, p in enumerate(predicted_events):
        if idx not in used_pred:
            error_breakdown["false_positives"].append(p.get("title", ""))

    type_acc = type_matches / matched_count if matched_count > 0 else 0.0
    date_acc = date_matches / matched_count if matched_count > 0 else 0.0
    ent_acc = (sum(entity_overlap_scores) / len(entity_overlap_scores)) if entity_overlap_scores else 0.0
    ev_acc = evidence_valid_count / matched_count if matched_count > 0 else 0.0

    return EventExtractionMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        type_accuracy=round(type_acc, 4),
        date_accuracy=round(date_acc, 4),
        entity_accuracy=round(ent_acc, 4),
        evidence_accuracy=round(ev_acc, 4),
        matched_events_count=matched_count,
        total_predicted=total_pred,
        total_ground_truth=total_gt,
        error_breakdown=error_breakdown
    )
