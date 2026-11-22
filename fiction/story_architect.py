"""
Story Architect Module for Elinity Fiction Engine.
Transforms a selected fictional scenario into a complete multi-chapter novel blueprint:
- Character blueprints (Protagonist, Antagonist, Allies, Informants) with motivations and backstories.
- Relational dynamics between characters.
- Multi-chapter progression arc (3 to 6 chapters).
- Persistent state initialization in PostgreSQL.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from fiction.db import (
    get_scenario_by_id,
    get_cluster_by_id,
    insert_story,
    insert_chapter,
    insert_character,
    insert_character_relationship,
    link_story_event,
    update_scenario_status
)
from fiction.utils import load_prompt, parse_llm_json
from llm_adapter import llm_client

logger = logging.getLogger("fiction.story_architect")

MANDATORY_DISCLAIMER = (
    "This is a fictional story inspired by real-world news events. "
    "The narrative connections, characters, motives, and developments are invented "
    "and do not imply that the underlying news events are causally related."
)


def _build_fallback_architecture(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback architecture blueprint if LLM is unavailable."""
    title = scenario.get("title", "The Silent Consensus")
    genre = scenario.get("genre", "Political Thriller")
    premise = scenario.get("premise", "")

    return {
        "title": title,
        "genre": genre,
        "synopsis": premise or f"A high-stakes {genre.lower()} unraveling interconnected international developments.",
        "world_setting": "Present day. Global financial centers, diplomatic safehouses, and server facilities.",
        "central_conflict": scenario.get("central_conflict", "Exposing covert telemetry manipulation before diplomatic catastrophe."),
        "ending_plan": "A tense confrontation at an international summit where unvarnished telemetry is revealed to the world.",
        "characters": [
            {
                "name": "Dr. Elena Vance",
                "role": "PROTAGONIST",
                "description": "Brilliant chief telemetry analyst with deep forensic instincts.",
                "motivations": "Vindicate her deceased mentor and prevent simulated conflict escalation.",
                "is_fictional": True
            },
            {
                "name": "Julian Mercer",
                "role": "ANTAGONIST",
                "description": "Charismatic defense syndicate executive orchestrating covert network operations.",
                "motivations": "Exploit border anxiety to secure billion-dollar automated defense contracts.",
                "is_fictional": True
            },
            {
                "name": "Kavita Rao",
                "role": "ALLY",
                "description": "Investigative cyber-intelligence reporter with encrypted access to backchannel feeds.",
                "motivations": "Expose defense lobbying corruption regardless of corporate pressure.",
                "is_fictional": True
            }
        ],
        "relationships": [
            {
                "character_a": "Dr. Elena Vance",
                "character_b": "Julian Mercer",
                "relationship_type": "FORMER_COLLEAGUE",
                "description": "Worked together at an aerospace lab before Mercer founded his private contractor firm."
            },
            {
                "character_a": "Dr. Elena Vance",
                "character_b": "Kavita Rao",
                "relationship_type": "MUTUAL_ALLIANCE",
                "description": "Rao acts as Vance's public conduit to reveal suppressed telemetry evidence."
            }
        ],
        "chapters": [
            {
                "chapter_number": 1,
                "title": "Anomalous Frequencies",
                "summary": "Elena discovers encrypted secondary signals embedded within standard commercial telemetry.",
                "focal_character": "Dr. Elena Vance",
                "key_revelations": ["The flight delay telemetry was not a glitch, but deliberate packet injection."]
            },
            {
                "chapter_number": 2,
                "title": "The Geneva Divergence",
                "summary": "At a ministerial summit, diplomatic negotiations stall over fabricated infrastructure logs.",
                "focal_character": "Dr. Elena Vance",
                "key_revelations": ["Julian Mercer's firm is the sole vendor offering the emergency replacement system."]
            },
            {
                "chapter_number": 3,
                "title": "Shadows in the Cold Corridor",
                "summary": "Elena and Kavita trace the signal's origin to an abandoned Arctic data enclave.",
                "focal_character": "Kavita Rao",
                "key_revelations": ["Physical servers show deliberate protocol overrides matching Mercer's proprietary code."]
            },
            {
                "chapter_number": 4,
                "title": "The Decryption Protocol",
                "summary": "During the final treaty session, Elena broadcasts the authenticated audit log, neutralizing the crisis.",
                "focal_character": "Dr. Elena Vance",
                "key_revelations": ["The truth is published globally; Mercer's syndicate is placed under international investigation."]
            }
        ],
        "disclaimer": MANDATORY_DISCLAIMER
    }


def architect_story(scenario_id: int) -> Dict[str, Any]:
    """
    Constructs a complete novel architecture from a selected scenario.
    Persists story, characters, character relationships, and chapter plans into PostgreSQL.
    """
    scenario = get_scenario_by_id(scenario_id)
    if not scenario:
        raise ValueError(f"Scenario ID {scenario_id} not found.")

    prompt_template = load_prompt("story_architecture.txt")
    prompt = prompt_template.format(
        title=scenario.get("title", ""),
        genre=scenario.get("genre", ""),
        logline=scenario.get("logline", ""),
        premise=scenario.get("premise", ""),
        verified_facts=json.dumps(scenario.get("verified_facts", [])),
        fictional_assumptions=json.dumps(scenario.get("fictional_assumptions", [])),
        fictional_characters=json.dumps(scenario.get("fictional_characters", [])),
        central_conflict=scenario.get("central_conflict", ""),
        narrative_stakes=scenario.get("narrative_stakes", "")
    )

    plan = None
    try:
        response = llm_client.generate(prompt=prompt, temperature=0.6, max_tokens=2500)
        parsed = parse_llm_json(response)
        if isinstance(parsed, dict) and "chapters" in parsed and len(parsed["chapters"]) >= 3:
            plan = parsed
    except Exception as exc:
        logger.warning(f"Story architecture LLM call failed for scenario {scenario_id}: {exc}")

    if not plan:
        plan = _build_fallback_architecture(scenario)

    # 1. Insert Story
    cluster_id = scenario.get("cluster_id")
    story_id = insert_story(
        scenario_id=scenario_id,
        cluster_id=cluster_id,
        title=plan.get("title", scenario.get("title")),
        genre=plan.get("genre", scenario.get("genre")),
        synopsis=plan.get("synopsis", scenario.get("premise")),
        world_setting=plan.get("world_setting", "Global Setting"),
        central_conflict=plan.get("central_conflict", scenario.get("central_conflict")),
        ending_plan=plan.get("ending_plan", ""),
        disclaimer=MANDATORY_DISCLAIMER,
        status="PLANNED"
    )

    # 2. Mark scenario as SELECTED
    update_scenario_status(scenario_id, "SELECTED")

    # 3. Insert Characters & build lookup
    char_id_map = {}
    for ch in plan.get("characters", []):
        name = ch.get("name")
        role = ch.get("role", "PROTAGONIST")
        desc = ch.get("description", "")
        motivations = ch.get("motivations", "")
        if name:
            c_id = insert_character(story_id, name, role, desc, motivations)
            char_id_map[name] = c_id

    # 4. Insert Character Relationships
    for rel in plan.get("relationships", []):
        ca_name = rel.get("character_a")
        cb_name = rel.get("character_b")
        if ca_name in char_id_map and cb_name in char_id_map:
            insert_character_relationship(
                story_id=story_id,
                char_a_id=char_id_map[ca_name],
                char_b_id=char_id_map[cb_name],
                rel_type=rel.get("relationship_type", "COLLEAGUE"),
                description=rel.get("description", "")
            )

    # 5. Link Cluster Events to Story
    if cluster_id:
        cluster = get_cluster_by_id(cluster_id)
        if cluster:
            for ev in cluster.get("events", []):
                link_story_event(
                    story_id=story_id,
                    event_id=ev["id"],
                    factual_elements=ev.get("title", ""),
                    fictional_transformation=f"Adapted into narrative background for {plan.get('title')}"
                )

    # 6. Insert Planned Chapter Placeholders
    created_chapters = []
    for ch_plan in plan.get("chapters", []):
        ch_num = ch_plan.get("chapter_number", len(created_chapters) + 1)
        ch_title = ch_plan.get("title", f"Chapter {ch_num}")
        ch_summary = ch_plan.get("summary", "")
        ch_id = insert_chapter(
            story_id=story_id,
            chapter_number=ch_num,
            title=ch_title,
            summary=ch_summary,
            content="",  # Blank initially until generated
            word_count=0,
            status="DRAFT"
        )
        ch_plan["id"] = ch_id
        created_chapters.append(ch_plan)

    logger.info(f"Successfully architected story {story_id}: '{plan.get('title')}' with {len(created_chapters)} chapters.")
    return {
        "story_id": story_id,
        "title": plan.get("title"),
        "genre": plan.get("genre"),
        "synopsis": plan.get("synopsis"),
        "chapters": created_chapters,
        "character_count": len(char_id_map)
    }
