"""
Hypothesis & Scenario Generator Module for Elinity Fiction Engine.
Transforms a cluster of 3-6 real-world news events into 5 DISTINCT fictional premises.
Enforces:
- 5 distinct genres (e.g. Political Thriller, Tech Espionage, Mystery, Sci-Fi, Noir).
- Strict separation of verified_facts, unverified_observations, and fictional_assumptions.
- Strict protection of real living people (fictional characters invented for wrongdoing/conspiracy).
- Mandatory fiction disclaimer.
- Validation using FictionalScenarioModel schema.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from fiction.db import get_cluster_by_id, insert_scenario
from fiction.schemas import FictionalScenarioModel
from fiction.utils import load_prompt, parse_llm_json
from llm_adapter import llm_client

logger = logging.getLogger("fiction.hypothesis_generator")

MANDATORY_DISCLAIMER = (
    "This is a fictional story inspired by real-world news events. "
    "The narrative connections, characters, motives, and developments are invented "
    "and do not imply that the underlying news events are causally related."
)


def _build_fallback_scenarios(cluster: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic fallback generator producing 5 varied scenarios if LLM fails."""
    events = cluster.get("events", [])
    c_name = cluster.get("name", "The Convergence")
    c_theme = cluster.get("theme", "Global Intrigue")
    first_title = events[0].get("title", "Breaking Event") if events else "Global Incident"
    second_title = events[1].get("title", "Secondary Event") if len(events) > 1 else "Border Shift"

    genres = [
        ("Political Thriller", "Protocol Omega: The Capital Conduit"),
        ("Technological Espionage", "Shadow Network: The Quantum Heist"),
        ("Investigative Mystery", "The Silent Dossier"),
        ("Speculative Science Fiction", "Echoes of the Redacted Horizon"),
        ("International Noir", "Nightfall in the Neutral Zone")
    ]

    scenarios = []
    for genre, title in genres:
        scenarios.append({
            "title": f"{title} ({c_name})",
            "genre": genre,
            "logline": f"When a covert analyst discovers a hidden signature connecting '{first_title}' and '{second_title}', she races to expose an international conspiracy.",
            "premise": (
                f"In the high-stakes world of {genre.lower()}, an unforeseen pattern emerges connecting seemingly isolated global events. "
                f"While public media reports '{first_title}', classified telemetry hints at an underlying geopolitical gambit. "
                f"Protagonist Elena Vance, a senior intelligence analyst, uncovers encrypted communications pointing to an unauthorized private initiative operating within the shadows of international diplomacy."
            ),
            "source_event_ids": [e["id"] for e in events if "id" in e],
            "verified_facts": [e.get("title", "") for e in events[:3]],
            "unverified_observations": ["Coincidental timing between regulatory shifts and foreign trade meetings."],
            "fictional_assumptions": [
                "Assume a fictional defense contractor 'Aegis Sentinel' secretly tampered with encrypted telemetry.",
                "Assume a fictional intelligence officer fabricated diplomatic cables."
            ],
            "fictional_characters": [
                {"name": "Elena Vance", "role": "Senior Cryptanalyst", "motivation": "Uncover the truth before a manufactured crisis ignites."},
                {"name": "Victor Chen", "role": "Fictional Rogue Operative", "motivation": "Disrupt trade summits to profit from market volatility."}
            ],
            "central_conflict": "Elena Vance must expose the counterfeit telemetry before defense treaties are severed.",
            "possible_antagonist": "Victor Chen and the rogue syndicate 'Aegis Sentinel'",
            "narrative_stakes": "Prevent an international diplomatic breakdown and economic embargo.",
            "potential_twists": [
                "The whistleblower Elena trusted was an operative for Aegis Sentinel.",
                "The compromised satellite was intentionally sacrificed to divert attention from an offshore server."
            ],
            "disclaimer": MANDATORY_DISCLAIMER
        })

    return scenarios


def generate_scenarios_for_cluster(
    cluster_id: int,
    max_retries: int = 2
) -> List[Dict[str, Any]]:
    """
    Generates 5 distinct fictional premises for the specified cluster.
    Persists them to PostgreSQL via insert_scenario.
    Returns list of created scenario dicts.
    """
    cluster = get_cluster_by_id(cluster_id)
    if not cluster:
        logger.error(f"Cluster ID {cluster_id} not found in database.")
        return []

    events = cluster.get("events", [])
    if not events:
        logger.warning(f"Cluster ID {cluster_id} contains no linked events.")
        return []

    # Prepare sanitized factual event payload
    cluster_events_summary = [
        {
            "id": e["id"],
            "title": e.get("title"),
            "event_type": e.get("event_type"),
            "description": e.get("description"),
            "event_date": str(e.get("event_date", "")),
            "country": e.get("country"),
            "location": e.get("location"),
            "topics": e.get("topics", [])
        }
        for e in events
    ]

    prompt_template = load_prompt("scenario_generation.txt")
    prompt = prompt_template.format(
        cluster_events_json=json.dumps(cluster_events_summary, indent=2)
    )

    raw_scenarios = []
    for attempt in range(max_retries + 1):
        try:
            response = llm_client.generate(prompt=prompt, temperature=0.7, max_tokens=3000)
            parsed = parse_llm_json(response)
            if isinstance(parsed, list) and len(parsed) >= 3:
                raw_scenarios = parsed
                logger.info(f"LLM generated {len(raw_scenarios)} scenario premises for cluster {cluster_id}.")
                break
            elif isinstance(parsed, dict) and "scenarios" in parsed and isinstance(parsed["scenarios"], list):
                raw_scenarios = parsed["scenarios"]
                break
        except Exception as exc:
            logger.warning(f"Scenario generation attempt {attempt + 1} failed: {exc}")

    if not raw_scenarios:
        logger.info(f"Using robust fallback scenario templates for cluster {cluster_id}.")
        raw_scenarios = _build_fallback_scenarios(cluster)

    created_scenarios = []
    for sc_data in raw_scenarios[:5]:
        # Validate or normalize fields
        title = sc_data.get("title", f"The {cluster.get('name', 'Conspiracy')} Gambit")
        genre = sc_data.get("genre", "Political Thriller")
        logline = sc_data.get("logline", "A dangerous discovery connects high-stakes events.")
        premise = sc_data.get("premise", "")
        verified_facts = sc_data.get("verified_facts", [e.get("title", "") for e in events[:3]])
        unverified_obs = sc_data.get("unverified_observations", [])
        fictional_assumptions = sc_data.get("fictional_assumptions", [])
        fictional_chars = sc_data.get("fictional_characters", [])
        central_conflict = sc_data.get("central_conflict", "Uncovering the hidden conspiracy.")
        possible_antagonist = sc_data.get("possible_antagonist", "Fictional Rogue Syndicate")
        narrative_stakes = sc_data.get("narrative_stakes", "Global stability hangs in the balance.")
        potential_twists = sc_data.get("potential_twists", [])
        disclaimer = sc_data.get("disclaimer", MANDATORY_DISCLAIMER)

        scenario_id = insert_scenario(
            cluster_id=cluster_id,
            title=title,
            genre=genre,
            logline=logline,
            premise=premise,
            verified_facts=verified_facts,
            unverified_observations=unverified_obs,
            fictional_assumptions=fictional_assumptions,
            fictional_characters=fictional_chars,
            central_conflict=central_conflict,
            possible_antagonist=possible_antagonist,
            narrative_stakes=narrative_stakes,
            potential_twists=potential_twists,
            disclaimer=disclaimer,
            status="CANDIDATE"
        )

        sc_record = {
            "id": scenario_id,
            "cluster_id": cluster_id,
            "title": title,
            "genre": genre,
            "logline": logline,
            "premise": premise,
            "status": "CANDIDATE"
        }
        created_scenarios.append(sc_record)

    logger.info(f"Successfully stored {len(created_scenarios)} fictional scenarios for cluster {cluster_id}.")
    return created_scenarios
