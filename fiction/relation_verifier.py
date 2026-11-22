"""
Relationship Verifier Module for Elinity Fiction Engine.
Applies rigorous evidence verification to distinguish verified facts from unverified associations.
Strict Rule: Temporal proximity or shared industry is NEVER classified as causal without explicit proof.
"""

import logging
from typing import Dict, Any, Tuple
from fiction.utils import load_prompt, parse_llm_json
from llm_adapter import llm_client

logger = logging.getLogger("fiction.relation_verifier")


def verify_event_relationship(
    event_a: Dict[str, Any],
    event_b: Dict[str, Any],
    heuristic_relation: str,
    shared_context: str = ""
) -> Tuple[str, bool, float, str]:
    """
    Evaluates whether two events share a genuine, source-backed relationship.
    Returns: (relation_type, is_verified, confidence, evidence_text)
    """
    # 1. Deterministic rules that do not require LLM calls
    if heuristic_relation == "SHARED_ENTITY":
        return (
            "SHARED_ENTITY",
            True,
            0.95,
            f"Verified: Both events involve verified entity participation ({shared_context})."
        )

    if heuristic_relation == "TEMPORAL_PROXIMITY":
        # Strictly unverified correlation: Timing alone does NOT imply causation
        return (
            "TEMPORAL_PROXIMITY",
            False,
            0.60,
            f"Unverified Association: Events occurred in close temporal proximity ({shared_context}). No causal link established."
        )

    if heuristic_relation == "CROSS_DOMAIN":
        return (
            "CROSS_DOMAIN",
            False,
            0.70,
            f"Narrative Thematic Correlation: Events span distinct domains ({shared_context}) with creative story potential."
        )

    # 2. For potential causal or contradiction links, verify via LLM
    try:
        prompt_template = load_prompt("relationship_verification.txt")
        prompt = prompt_template.format(
            event_a_title=event_a.get("title", ""),
            event_a_date=str(event_a.get("event_date", "Unknown")),
            event_a_desc=event_a.get("description", ""),
            event_a_entities=", ".join([e.get("canonical_name", "") for e in event_a.get("entities", [])]),
            event_a_topics=", ".join(event_a.get("topics", [])),
            event_b_title=event_b.get("title", ""),
            event_b_date=str(event_b.get("event_date", "Unknown")),
            event_b_desc=event_b.get("description", ""),
            event_b_entities=", ".join([e.get("canonical_name", "") for e in event_b.get("entities", [])]),
            event_b_topics=", ".join(event_b.get("topics", [])),
            shared_context=shared_context
        )

        raw = llm_client.generate(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=600
        )
        parsed = parse_llm_json(raw)
        if parsed and isinstance(parsed, dict):
            rel_type = parsed.get("relation_type", heuristic_relation).upper()
            is_verified = bool(parsed.get("is_verified", False))
            # Safety gate: A causal link is verified ONLY if is_verified is True
            if rel_type == "SOURCE_REPORTED_CAUSAL_LINK" and not is_verified:
                rel_type = "SEMANTIC_SIMILARITY"
            confidence = float(parsed.get("confidence", 0.75))
            evidence = str(parsed.get("evidence_text", "Evaluated relationship."))
            return rel_type, is_verified, confidence, evidence

    except Exception as e:
        logger.warning(f"LLM relationship verification failed ({e}). Falling back to heuristic.")

    return (
        heuristic_relation,
        False,
        0.5,
        f"Hypothesized relationship based on {heuristic_relation.lower()}."
    )
