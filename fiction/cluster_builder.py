"""
Cluster Builder Module for Elinity Fiction Engine.
Synthesizes narrative event clusters containing 3 to 6 distinct events.
Ensures:
- 3 to 6 distinct real-world events per cluster.
- Cross-domain narrative tension (combining e.g. technology, geopolitics, business).
- Multi-hop relationship connectivity.
- Generates evocative cluster titles, themes, and summaries.
"""

import json
import logging
import uuid
from typing import List, Dict, Any, Optional
from fiction.db import (
    get_all_events,
    get_event_relations,
    insert_cluster
)
from fiction.event_graph import build_graph_from_db
from fiction.utils import parse_llm_json
from llm_adapter import llm_client

logger = logging.getLogger("fiction.cluster_builder")


def _generate_cluster_metadata_llm(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generates thematic name, theme, and narrative summary for a group of events."""
    events_brief = [
        {
            "id": e["id"],
            "title": e.get("title"),
            "event_type": e.get("event_type"),
            "topics": e.get("topics", []),
            "country": e.get("country"),
            "entities": [ent.get("canonical_name") for ent in e.get("entities", [])[:4]]
        }
        for e in events
    ]

    prompt = f"""You are a master fiction editor and story curator.
Given these {len(events)} real-world news events:
{json.dumps(events_brief, indent=2)}

Create an evocative, dramatic cluster concept that binds these events into a fictional storytelling launchpad.
Return a valid JSON object matching:
{{
  "name": "Evocative Cluster Name (e.g. The Silicon Concordat / Arctic Shadows / The Diplomatic Signal)",
  "theme": "Core narrative theme (e.g. Covert Cyber-Geopolitics / Critical Infrastructure Espionage / Autonomous Warfare)",
  "summary": "2-3 sentences explaining the overarching narrative tension connecting these events.",
  "domains": ["Technology", "Geopolitics", "Defense"]
}}
"""
    try:
        response = llm_client.generate(prompt=prompt, temperature=0.5, max_tokens=500)
        parsed = parse_llm_json(response)
        if isinstance(parsed, dict) and "name" in parsed:
            return parsed
    except Exception as exc:
        logger.warning(f"LLM cluster metadata generation failed: {exc}, using fallback heuristic.")

    # Fallback heuristic if LLM fails
    all_topics = set()
    for e in events:
        all_topics.update(e.get("topics", []))
    domains = list(all_topics)[:3] or ["Global Affairs", "Security"]
    first_title = events[0].get("title", "Global Events")

    return {
        "name": f"The {domains[0].title()} Convergence",
        "theme": f"Interconnected events spanning {', '.join(domains)}",
        "summary": f"A dynamic convergence of events beginning with '{first_title}' and intersecting critical global interests.",
        "domains": domains
    }


def build_event_clusters(
    min_events: int = 3,
    max_events: int = 6,
    max_clusters: int = 5
) -> List[Dict[str, Any]]:
    """
    Constructs narrative clusters from stored events and relations.
    Persists them to PostgreSQL via insert_cluster.
    Returns list of created cluster dicts.
    """
    events = get_all_events(limit=100)
    if len(events) < min_events:
        logger.warning(f"Only {len(events)} events found in DB; minimum required is {min_events}.")
        return []

    relations = get_event_relations(limit=300)

    # 1. Build graph representation
    graph = build_graph_from_db(events, relations)

    # 2. Extract candidate event groups
    candidate_groups = graph.extract_candidate_clusters(min_events=min_events, max_events=max_events)
    logger.info(f"Discovered {len(candidate_groups)} raw candidate cluster groups from event graph.")

    # Event lookup map
    events_map = {e["id"]: e for e in events}

    # If graph didn't yield enough candidates, group by topic/temporal proximity
    if not candidate_groups:
        chunks = [events[i:i + 4] for i in range(0, min(len(events), 16), 4)]
        candidate_groups = [[e["id"] for e in chunk] for chunk in chunks if len(chunk) >= min_events]

    created_clusters = []

    for group in candidate_groups[:max_clusters]:
        cluster_events = [events_map[eid] for eid in group if eid in events_map]
        if len(cluster_events) < min_events:
            continue

        meta = _generate_cluster_metadata_llm(cluster_events)
        cluster_code = f"CLUSTER-{uuid.uuid4().hex[:8].upper()}"

        cluster_record = {
            "cluster_code": cluster_code,
            "name": meta.get("name", "Narrative Convergence"),
            "theme": meta.get("theme", "Cross-Domain Narrative"),
            "summary": meta.get("summary", ""),
            "domains": meta.get("domains", ["Geopolitics", "Technology"]),
            "event_ids": group
        }

        cluster_id = insert_cluster(cluster_record)
        if cluster_id:
            cluster_record["id"] = cluster_id
            created_clusters.append(cluster_record)
            logger.info(f"Persisted cluster ID {cluster_id}: {cluster_record['name']} with {len(group)} events.")

    return created_clusters
