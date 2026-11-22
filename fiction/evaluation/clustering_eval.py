"""
Event Clustering Evaluator for Elinity Fiction Evaluation Framework.
Measures:
- B-cubed Precision, B-cubed Recall, B-cubed F1
- Cluster Purity & Cluster Completeness
- Duplicate and overlapping event detection
- Error reporting for over-merging and over-splitting
"""

import logging
from typing import List, Dict, Any, Set
from fiction.evaluation.schemas import ClusteringMetrics

logger = logging.getLogger("fiction.evaluation.clustering")


def evaluate_event_clustering(
    predicted_clusters: List[List[str]],
    ground_truth_clusters: List[List[str]]
) -> ClusteringMetrics:
    """
    Evaluates predicted event clusters against ground-truth clusters using standard B-cubed metrics.
    Predicted clusters: list of event ID lists, e.g. [['ev1', 'ev2', 'ev3'], ['ev4', 'ev5']]
    Ground truth: list of event ID lists
    """
    if not predicted_clusters and not ground_truth_clusters:
        return ClusteringMetrics(
            bcubed_precision=1.0, bcubed_recall=1.0, bcubed_f1=1.0,
            cluster_purity=1.0, cluster_completeness=1.0
        )

    # Build membership lookups: item -> set of items in same cluster
    pred_membership: Dict[str, Set[str]] = {}
    for cl in predicted_clusters:
        cl_set = set(str(e) for e in cl)
        for item in cl_set:
            pred_membership[item] = cl_set

    gt_membership: Dict[str, Set[str]] = {}
    for cl in ground_truth_clusters:
        cl_set = set(str(e) for e in cl)
        for item in cl_set:
            gt_membership[item] = cl_set

    all_items = list(set(list(pred_membership.keys()) + list(gt_membership.keys())))
    if not all_items:
        return ClusteringMetrics(
            bcubed_precision=1.0, bcubed_recall=1.0, bcubed_f1=1.0,
            cluster_purity=1.0, cluster_completeness=1.0
        )

    # B-cubed Precision & Recall
    prec_scores = []
    rec_scores = []

    for item in all_items:
        c_pred = pred_membership.get(item, {item})
        c_gt = gt_membership.get(item, {item})

        intersect = len(c_pred & c_gt)
        prec_scores.append(intersect / len(c_pred))
        rec_scores.append(intersect / len(c_gt))

    bcubed_prec = sum(prec_scores) / len(prec_scores)
    bcubed_rec = sum(rec_scores) / len(rec_scores)
    bcubed_f1 = (2 * bcubed_prec * bcubed_rec / (bcubed_prec + bcubed_rec)) if (bcubed_prec + bcubed_rec) > 0 else 0.0

    # Cluster Purity: For each predicted cluster, find majority ground-truth class
    purity_counts = 0
    total_pred_items = 0
    errors = []

    for cl in predicted_clusters:
        cl_items = [str(e) for e in cl]
        total_pred_items += len(cl_items)
        if not cl_items:
            continue

        # Count ground truth cluster memberships
        counts = {}
        for item in cl_items:
            gt_id = None
            for idx, gt_cl in enumerate(ground_truth_clusters):
                if item in [str(x) for x in gt_cl]:
                    gt_id = idx
                    break
            counts[gt_id] = counts.get(gt_id, 0) + 1

        majority_count = max(counts.values()) if counts else 0
        purity_counts += majority_count

        # Detect impure cluster (combining unrelated events)
        if len(counts) > 1 and majority_count < len(cl_items):
            errors.append({
                "type": "IMPURE_CLUSTER",
                "cluster_size": len(cl_items),
                "majority_ratio": majority_count / len(cl_items),
                "events": cl_items
            })

    cluster_purity = purity_counts / total_pred_items if total_pred_items > 0 else 1.0

    # Completeness
    completeness_counts = 0
    total_gt_items = 0
    for gt_cl in ground_truth_clusters:
        gt_items = [str(e) for e in gt_cl]
        total_gt_items += len(gt_items)
        if not gt_items:
            continue

        counts = {}
        for item in gt_items:
            pred_id = None
            for idx, pr_cl in enumerate(predicted_clusters):
                if item in [str(x) for x in pr_cl]:
                    pred_id = idx
                    break
            counts[pred_id] = counts.get(pred_id, 0) + 1

        completeness_counts += max(counts.values()) if counts else 0

    completeness = completeness_counts / total_gt_items if total_gt_items > 0 else 1.0

    # Check for duplicates across predicted clusters
    seen_events = set()
    duplicate_count = 0
    for cl in predicted_clusters:
        for e in cl:
            e_str = str(e)
            if e_str in seen_events:
                duplicate_count += 1
            seen_events.add(e_str)

    return ClusteringMetrics(
        bcubed_precision=round(bcubed_prec, 4),
        bcubed_recall=round(bcubed_rec, 4),
        bcubed_f1=round(bcubed_f1, 4),
        cluster_purity=round(cluster_purity, 4),
        cluster_completeness=round(completeness, 4),
        duplicate_events_detected=duplicate_count,
        overlapping_events_detected=duplicate_count,
        cluster_error_report=errors[:15]
    )
