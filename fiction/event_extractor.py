"""
Event Extractor Module for Elinity Fiction Engine.
Extracts structured real-world events from news articles with full provenance,
strict date separation, and entity linking.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from fiction.utils import load_prompt, parse_llm_json, parse_iso_date
from fiction.schemas import ExtractedEvent, EventExtractionBatch
from fiction.db import insert_fiction_event, insert_event_source
from fiction.entity_resolver import resolve_and_persist_entities_for_event
from llm_adapter import llm_client

logger = logging.getLogger("fiction.event_extractor")


def extract_events_from_article(article: Dict[str, Any], max_retries: int = 2) -> List[int]:
    """
    Extracts structured real-world events from a single article using LLM.
    Returns list of created fiction_events IDs.
    Preserves strict provenance linking each event to the source article and verbatim evidence.
    """
    article_id = article.get("id")
    title = article.get("title", "")
    content = article.get("cleaned_content", "")
    url = article.get("url", "")
    publisher = article.get("publisher", "Major News Feed")
    published_at = article.get("published_at")

    if not content or len(content.strip()) < 50:
        logger.info(f"Skipping article ID {article_id} due to insufficient content length.")
        return []

    prompt_template = load_prompt("event_extraction.txt")
    prompt = prompt_template.format(
        title=title,
        publisher=publisher,
        published_at=str(published_at),
        url=url,
        content=content[:3500]  # Window for context
    )

    created_event_ids = []

    for attempt in range(1, max_retries + 1):
        try:
            raw_response = llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # Low temperature for strict factual extraction
                max_tokens=1800
            )

            parsed_data = parse_llm_json(raw_response)
            if not parsed_data:
                logger.warning(f"Attempt {attempt}: Failed to parse JSON from event extraction LLM response.")
                continue

            events_raw = parsed_data.get("events", []) if isinstance(parsed_data, dict) else (parsed_data if isinstance(parsed_data, list) else [])
            if not events_raw:
                logger.info(f"Article ID {article_id} yielded 0 distinct events.")
                return []

            for item in events_raw:
                try:
                    # Validate schema
                    event_obj = ExtractedEvent(**item)
                except Exception as val_err:
                    logger.warning(f"Validation error on extracted event: {val_err}. Skipping item.")
                    continue

                event_date = parse_iso_date(str(event_obj.event_date)) if event_obj.event_date else None

                # Persist event in Neon DB
                event_id = insert_fiction_event(
                    event_type=event_obj.event_type.upper(),
                    title=event_obj.title,
                    description=event_obj.description,
                    main_action=event_obj.main_action,
                    event_date=event_date,
                    date_precision=event_obj.date_precision.upper(),
                    location=event_obj.location or "",
                    country=event_obj.country or "",
                    topics=event_obj.topics,
                    extraction_confidence=event_obj.extraction_confidence
                )

                # Persist source provenance with verbatim evidence excerpts
                evidence_text = "\n---\n".join(event_obj.evidence_excerpts) if event_obj.evidence_excerpts else event_obj.description
                insert_event_source(
                    event_id=event_id,
                    article_id=article_id,
                    source_url=url,
                    evidence_excerpt=evidence_text,
                    publisher=publisher,
                    published_at=published_at if isinstance(published_at, datetime) else None
                )

                # Resolve and link entities
                resolve_and_persist_entities_for_event(
                    event_id=event_id,
                    participants=event_obj.participants,
                    organizations=event_obj.organizations,
                    governments=event_obj.government_entities
                )

                created_event_ids.append(event_id)

            logger.info(f"Article ID {article_id} ('{title[:40]}...'): Extracted & stored {len(created_event_ids)} events.")
            return created_event_ids

        except Exception as e:
            logger.error(f"Attempt {attempt} error extracting events from article ID {article_id}: {e}")

    return created_event_ids


def batch_extract_events(articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Processes a batch of articles and records extracted events."""
    total_events = 0
    article_count = len(articles)

    for idx, art in enumerate(articles, 1):
        event_ids = extract_events_from_article(art)
        total_events += len(event_ids)
        if idx % 10 == 0:
            logger.info(f"Event extraction progress: {idx}/{article_count} articles processed, {total_events} events created.")

    return {
        "articles_processed": article_count,
        "events_created": total_events
    }
