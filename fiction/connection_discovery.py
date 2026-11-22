"""
Event Relationship Discovery Engine for Elinity Fiction Engine.
Discovers multi-dimensional relationships between real-world events:
1. SHARED_ENTITY
2. TEMPORAL_PROXIMITY
3. SEMANTIC_SIMILARITY
4. CROSS_DOMAIN
5. SOURCE_REPORTED_CAUSAL_LINK
6. CONTRADICTION
"""

import logging
from datetime import date
from typing import List, Dict, Any, Tuple
from fiction.db import get_all_events, insert_event_relation
from fiction.relation_verifier import verify_event_relationship

logger = logging.getLogger("fiction.connection_discovery")


def discover_event_relationships(events: List[Dict[str, Any]] = None, max_pairs: int = 150) -> int:
    """
    Analyzes pairs of events to discover candidate relationships.
    Persists validated relationships to fiction_event_relations.
    """
    if not events:
        events = get_all_events(limit=80)

    if len(events) < 2:
        logger.info("Fewer than 2 events available for relationship discovery.")
        return 0

    relations_created = 0
    pairs_evaluated = 0

    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            if pairs_evaluated >= max_pairs:
                break

            e1 = events[i]
            e2 = events[j]
            pairs_evaluated += 1

            candidate_type = None
            shared_info = ""
            shared_ent_id = None

            # 1. Check Shared Entities
            e1_ents = {ent.get("canonical_name"): ent.get("entity_id") for ent in e1.get("entities", []) if ent.get("canonical_name")}
            e2_ents = {ent.get("canonical_name"): ent.get("entity_id") for ent in e2.get("entities", []) if ent.get("canonical_name")}
            common_ents = set(e1_ents.keys()) & set(e2_ents.keys())

            if common_ents:
                candidate_type = "SHARED_ENTITY"
                matched_name = list(common_ents)[0]
                shared_ent_id = e1_ents[matched_name]
                shared_info = f"Common entity: {', '.join(common_ents)}"

            # 2. Check Temporal Proximity (events within <= 3 days)
            elif e1.get("event_date") and e2.get("event_date"):
                d1 = e1["event_date"] if isinstance(e1["event_date"], date) else None
                d2 = e2["event_date"] if isinstance(e2["event_date"], date) else None
                if d1 and d2:
                    delta = abs((d1 - d2).days)
                    if delta <= 3:
                        candidate_type = "TEMPORAL_PROXIMITY"
                        shared_info = f"Occurred {delta} day(s) apart ({d1} vs {d2})"

            # 3. Check Cross-Domain Potential (different topics but geographic or institutional overlap)
            e1_topics = set(e1.get("topics") or [])
            e2_topics = set(e2.get("topics") or [])
            if not candidate_type and e1_topics and e2_topics and not (e1_topics & e2_topics):
                if e1.get("country") and e2.get("country") and e1.get("country") == e2.get("country"):
                    candidate_type = "CROSS_DOMAIN"
                    shared_info = f"Shared country '{e1.get('country')}' across distinct domains: {list(e1_topics)[:2]} vs {list(e2_topics)[:2]}"

            # 4. Check Semantic Similarity (shared topics or key action words)
            elif not candidate_type and (e1_topics & e2_topics):
                candidate_type = "SEMANTIC_SIMILARITY"
                shared_info = f"Shared topics: {', '.join(e1_topics & e2_topics)}"

            if candidate_type:
                rel_type, is_verified, confidence, evidence = verify_event_relationship(
                    event_a=e1,
                    event_b=e2,
                    heuristic_relation=candidate_type,
                    shared_context=shared_info
                )

                rel_id = insert_event_relation(
                    source_event_id=e1["id"],
                    target_event_id=e2["id"],
                    relation_type=rel_type,
                    is_verified=is_verified,
                    confidence=confidence,
                    evidence_text=evidence,
                    shared_entity_id=shared_ent_id
                )
                if rel_id > 0:
                    relations_created += 1

    logger.info(f"Discovered and persisted {relations_created} event relationships across {pairs_evaluated} candidate pairs.")
    return relations_created
