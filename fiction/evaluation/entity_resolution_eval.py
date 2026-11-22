"""
Entity Resolution Evaluator for Elinity Fiction Evaluation Framework.
Measures:
- Entity-linking accuracy, Precision, Recall, F1
- False Merge Rate (Incorrectly merging distinct real-world entities -- High severity!)
- False Split Rate (Failing to link distinct mentions of the same entity)
- Detailed entity-level error reporting
"""

import logging
from typing import List, Dict, Any, Set, Tuple
from fiction.evaluation.schemas import EntityResolutionMetrics

logger = logging.getLogger("fiction.evaluation.entity_resolution")


def evaluate_entity_resolution(
    predicted_entities: List[Dict[str, Any]],
    ground_truth_entities: List[Dict[str, Any]]
) -> EntityResolutionMetrics:
    """
    Evaluates entity linking and canonicalization.
    Pairs predicted canonical names against ground truth aliases.
    """
    if not ground_truth_entities and not predicted_entities:
        return EntityResolutionMetrics(
            entity_linking_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0,
            false_merge_rate=0.0, false_split_rate=0.0
        )

    # Lookup maps: mention -> canonical
    pred_map = {}
    for p in predicted_entities:
        c_name = p.get("canonical_name", "").strip().lower()
        pred_map[c_name] = c_name
        for alias in p.get("aliases", []):
            pred_map[alias.strip().lower()] = c_name

    gt_map = {}
    for g in ground_truth_entities:
        c_name = g.get("name", "").strip().lower()
        gt_map[c_name] = c_name
        for alias in g.get("aliases", []):
            gt_map[alias.strip().lower()] = c_name

    # Check pairwise co-references
    all_mentions = list(set(list(pred_map.keys()) + list(gt_map.keys())))
    total_pairs = 0
    correct_links = 0
    false_merges = 0
    false_splits = 0
    errors = []

    for i in range(len(all_mentions)):
        for j in range(i + 1, len(all_mentions)):
            m1 = all_mentions[i]
            m2 = all_mentions[j]

            gt_same = (m1 in gt_map and m2 in gt_map and gt_map[m1] == gt_map[m2])
            pred_same = (m1 in pred_map and m2 in pred_map and pred_map[m1] == pred_map[m2])

            total_pairs += 1

            if gt_same and pred_same:
                correct_links += 1
            elif not gt_same and not pred_same:
                correct_links += 1
            elif not gt_same and pred_same:
                # FALSE MERGE: Two different entities mistakenly merged into one!
                false_merges += 1
                errors.append({
                    "error_type": "FALSE_MERGE",
                    "mentions": [m1, m2],
                    "predicted_canonical": pred_map[m1],
                    "gt_entities": [gt_map.get(m1), gt_map.get(m2)]
                })
            elif gt_same and not pred_same:
                # FALSE SPLIT: Same entity split into multiple
                false_splits += 1
                errors.append({
                    "error_type": "FALSE_SPLIT",
                    "mentions": [m1, m2],
                    "gt_canonical": gt_map[m1]
                })

    accuracy = correct_links / total_pairs if total_pairs > 0 else 1.0
    false_merge_rate = false_merges / total_pairs if total_pairs > 0 else 0.0
    false_split_rate = false_splits / total_pairs if total_pairs > 0 else 0.0

    # Entity level precision / recall
    tp = sum(1 for m in all_mentions if m in pred_map and m in gt_map and pred_map[m] == gt_map[m])
    fp = sum(1 for m in all_mentions if m in pred_map and (m not in gt_map or pred_map[m] != gt_map.get(m)))
    fn = sum(1 for m in all_mentions if m in gt_map and (m not in pred_map or gt_map[m] != pred_map.get(m)))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return EntityResolutionMetrics(
        entity_linking_accuracy=round(accuracy, 4),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        false_merge_rate=round(false_merge_rate, 4),
        false_split_rate=round(false_split_rate, 4),
        errors=errors[:25]
    )
