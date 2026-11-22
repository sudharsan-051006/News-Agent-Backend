"""
Relationship Discovery Evaluator for Elinity Fiction Evaluation Framework.
Measures:
- Precision@K, Recall@K, F1
- Evidence-support rate
- Unsupported relationship rate
- Relationship type accuracy
- False Causal Relationship Rate (Critical safeguard: Flags when temporal proximity or shared entities are claimed as causal!)
- Unsupported claims report
"""

import logging
from typing import List, Dict, Any, Tuple
from collections import defaultdict
from fiction.evaluation.schemas import RelationshipMetrics

logger = logging.getLogger("fiction.evaluation.relationship")


def evaluate_relationship_discovery(
    predicted_relations: List[Dict[str, Any]],
    ground_truth_relations: List[Dict[str, Any]],
    k: int = 5
) -> RelationshipMetrics:
    """
    Evaluates discovered relationships against ground-truth event pairs.
    Computes ranking metrics (Precision@K) and safety metrics (False Causal Rate).
    """
    if not ground_truth_relations and not predicted_relations:
        return RelationshipMetrics(
            precision_at_k=1.0, recall_at_k=1.0, f1=1.0,
            evidence_support_rate=1.0, unsupported_relationship_rate=0.0,
            relationship_type_accuracy=1.0, false_causal_relationship_rate=0.0
        )

    # Key representation: frozenset([source_id, target_id])
    def pair_key(s_id, t_id):
        return frozenset([str(s_id), str(t_id)])

    gt_dict = {}
    for g in ground_truth_relations:
        key = pair_key(g.get("source_event_id"), g.get("target_event_id"))
        gt_dict[key] = g

    # Rank predicted relations by confidence DESC
    sorted_preds = sorted(predicted_relations, key=lambda x: x.get("confidence", 0.5), reverse=True)
    top_k_preds = sorted_preds[:k]

    # Precision@K
    tp_at_k = 0
    type_matches = 0
    evidence_supported_count = 0
    false_causal_count = 0
    unsupported_claims = []

    for pred in top_k_preds:
        p_key = pair_key(pred.get("source_event_id"), pred.get("target_event_id"))
        p_type = pred.get("relation_type", "").upper()
        p_verified = pred.get("is_verified", False)

        if p_key in gt_dict:
            gt_item = gt_dict[p_key]
            gt_type = gt_item.get("relation_type", "").upper()
            gt_classification = gt_item.get("classification", "EVIDENCE_BACKED")

            # Matched related pair
            if gt_type != "UNRELATED":
                tp_at_k += 1

            # Type match
            if p_type == gt_type:
                type_matches += 1

            # Evidence verification check
            if p_verified and gt_classification in ["EVIDENCE_BACKED", "CONTEXTUALLY_PLAUSIBLE"]:
                evidence_supported_count += 1
            elif p_verified and gt_classification in ["UNSUPPORTED", "SPECULATIVE"]:
                # CRITICAL: Claimed verified or causal without backing!
                unsupported_claims.append({
                    "pair": list(p_key),
                    "claimed_type": p_type,
                    "gt_classification": gt_classification,
                    "evidence_text": pred.get("evidence_text", "")
                })

            # False Causal check: e.g. claiming causal when GT is temporal proximity or unrelated
            if "CAUSAL" in p_type and ("TEMPORAL" in gt_type or gt_type == "UNRELATED"):
                false_causal_count += 1
                unsupported_claims.append({
                    "error_type": "FALSE_CAUSAL_CLAIM",
                    "pair": list(p_key),
                    "claimed": p_type,
                    "ground_truth": gt_type
                })
        else:
            # Unseen pair: check if flagged as verified without proof
            if p_verified:
                unsupported_claims.append({
                    "pair": list(p_key),
                    "claimed_type": p_type,
                    "reason": "Unannotated pair asserted as verified fact"
                })

    prec_at_k = tp_at_k / len(top_k_preds) if top_k_preds else 0.0
    relevant_gt = sum(1 for g in ground_truth_relations if g.get("relation_type", "").upper() != "UNRELATED")
    rec_at_k = tp_at_k / min(k, relevant_gt) if relevant_gt > 0 else 1.0
    f1 = (2 * prec_at_k * rec_at_k / (prec_at_k + rec_at_k)) if (prec_at_k + rec_at_k) > 0 else 0.0

    evidence_rate = evidence_supported_count / len(top_k_preds) if top_k_preds else 0.0
    unsupported_rate = len(unsupported_claims) / len(top_k_preds) if top_k_preds else 0.0
    type_acc = min(1.0, type_matches / len(top_k_preds)) if top_k_preds else 0.0
    false_causal_rate = false_causal_count / len(top_k_preds) if top_k_preds else 0.0

    return RelationshipMetrics(
        precision_at_k=round(prec_at_k, 4),
        recall_at_k=round(rec_at_k, 4),
        f1=round(f1, 4),
        evidence_support_rate=round(evidence_rate, 4),
        unsupported_relationship_rate=round(unsupported_rate, 4),
        relationship_type_accuracy=round(type_acc, 4),
        false_causal_relationship_rate=round(false_causal_rate, 4),
        confusion_matrix={"tp": tp_at_k, "k": k, "unsupported": len(unsupported_claims)},
        unsupported_claims=unsupported_claims
    )
