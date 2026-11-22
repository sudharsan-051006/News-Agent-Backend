"""
Entity Resolution Module for Elinity Fiction Engine.
Identifies recurring real-world entities across events, resolves aliases,
and links participation roles without over-merging.
"""

import re
import logging
from typing import Dict, List, Tuple, Optional
from fiction.db import get_or_create_entity, link_event_entity

logger = logging.getLogger("fiction.entity_resolver")

# Canonical aliases dictionary for common geopolitical and international entities
CANONICAL_ALIASES: Dict[str, Tuple[str, str]] = {
    "us": ("United States", "GPE"),
    "u.s.": ("United States", "GPE"),
    "usa": ("United States", "GPE"),
    "u.s.a.": ("United States", "GPE"),
    "united states": ("United States", "GPE"),
    "united states of america": ("United States", "GPE"),
    "uk": ("United Kingdom", "GPE"),
    "u.k.": ("United Kingdom", "GPE"),
    "britain": ("United Kingdom", "GPE"),
    "great britain": ("United Kingdom", "GPE"),
    "eu": ("European Union", "INSTITUTION"),
    "e.u.": ("European Union", "INSTITUTION"),
    "european union": ("European Union", "INSTITUTION"),
    "un": ("United Nations", "INSTITUTION"),
    "u.n.": ("United Nations", "INSTITUTION"),
    "united nations": ("United Nations", "INSTITUTION"),
    "who": ("World Health Organization", "INSTITUTION"),
    "w.h.o.": ("World Health Organization", "INSTITUTION"),
    "nato": ("North Atlantic Treaty Organization", "INSTITUTION"),
    "russia": ("Russia", "GPE"),
    "russian federation": ("Russia", "GPE"),
    "china": ("China", "GPE"),
    "prc": ("China", "GPE"),
    "people's republic of china": ("China", "GPE"),
    "india": ("India", "GPE"),
    "bharat": ("India", "GPE"),
    "narendra modi": ("Narendra Modi", "PERSON"),
    "pm modi": ("Narendra Modi", "PERSON"),
    "modi": ("Narendra Modi", "PERSON"),
    "n. modi": ("Narendra Modi", "PERSON"),
    "prime minister narendra modi": ("Narendra Modi", "PERSON"),
    "google": ("Google", "ORG"),
    "google llc": ("Google", "ORG"),
    "white house": ("White House", "INSTITUTION"),
    "the white house": ("White House", "INSTITUTION"),
    "openai": ("OpenAI", "ORG"),
}


def normalize_entity_name(name: str) -> str:
    """Normalizes whitespace, casing, and standard corporate/diplomatic suffixes."""
    clean = re.sub(r"\s+", " ", name.strip())
    # Strip common possessives
    clean = re.sub(r"'s$", "", clean, flags=re.IGNORECASE)
    return clean


def resolve_entity(raw_name: str, fallback_type: str = "ORG") -> Tuple[str, str, List[str]]:
    """
    Resolves a raw entity string into its canonical name, entity type, and alias list.
    Avoids incorrectly merging entities with distinct identities.
    """
    normalized = normalize_entity_name(raw_name)
    lookup_key = normalized.lower()

    if lookup_key in CANONICAL_ALIASES:
        canonical, ent_type = CANONICAL_ALIASES[lookup_key]
        aliases = [normalized] if normalized != canonical else []
        return canonical, ent_type, aliases

    # Heuristic entity typing if fallback is general
    ent_type = fallback_type
    if any(title in normalized for title in ["President", "Prime Minister", "Minister", "Dr.", "CEO", "Director", "Judge", "General"]):
        ent_type = "PERSON"
    elif any(term in normalized for term in ["Ministry", "Department", "Court", "Commission", "Parliament", "Congress", "Senate"]):
        ent_type = "INSTITUTION"
    elif any(term in normalized for term in ["Corp", "Inc", "LLC", "Technologies", "Tech", "Airlines", "Bank", "Ltd", "Holdings"]):
        ent_type = "ORG"

    return normalized, ent_type, []


def resolve_and_persist_entities_for_event(
    event_id: int,
    participants: List[str],
    organizations: List[str],
    governments: List[str]
) -> List[int]:
    """
    Resolves all extracted entities for an event, persists canonical records in Neon DB,
    and links event-entity participation with designated roles.
    """
    entity_ids = []

    # 1. Individual Participants (Actors/Spokespersons)
    for p in participants:
        if not p or len(p.strip()) < 2:
            continue
        canonical, ent_type, aliases = resolve_entity(p, fallback_type="PERSON")
        ent_id = get_or_create_entity(canonical, ent_type, aliases)
        link_event_entity(event_id, ent_id, role="ACTOR")
        entity_ids.append(ent_id)

    # 2. Organizations
    for org in organizations:
        if not org or len(org.strip()) < 2:
            continue
        canonical, ent_type, aliases = resolve_entity(org, fallback_type="ORG")
        ent_id = get_or_create_entity(canonical, ent_type, aliases)
        link_event_entity(event_id, ent_id, role="ORGANIZATION")
        entity_ids.append(ent_id)

    # 3. Government Entities
    for gov in governments:
        if not gov or len(gov.strip()) < 2:
            continue
        canonical, ent_type, aliases = resolve_entity(gov, fallback_type="INSTITUTION")
        ent_id = get_or_create_entity(canonical, ent_type, aliases)
        link_event_entity(event_id, ent_id, role="GOVERNMENT")
        entity_ids.append(ent_id)

    return entity_ids
