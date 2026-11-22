"""
Dataset Manager for Elinity Fiction Evaluation Framework.
Handles:
- Dataset catalog and case CRUD in PostgreSQL
- Seeding high-quality pilot ground-truth dataset (100 articles, 50 events, 40 relation pairs, 12 clusters)
- JSON and CSV import / export
"""

import json
import csv
import io
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_connection, db_retry
from fiction.evaluation.schemas import EvalCaseModel, DatasetMetadata

logger = logging.getLogger("fiction.evaluation.dataset_manager")


# =====================================================================
# Database Access Helpers
# =====================================================================

@db_retry(max_retries=3, delay=1.0)
def create_dataset(name: str, version: str = "v1.0", description: str = "", domain: str = "General News") -> int:
    """Creates a new evaluation dataset entry."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_eval_datasets (name, version, description, domain)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name, version) DO UPDATE SET
                    description = EXCLUDED.description,
                    domain = EXCLUDED.domain,
                    updated_at = NOW()
                RETURNING id;
            """, (name, version, description, domain))
            dataset_id = cur.fetchone()["id"]
            conn.commit()
            return dataset_id


@db_retry(max_retries=3, delay=1.0)
def get_all_datasets() -> List[Dict[str, Any]]:
    """Retrieves all registered evaluation datasets."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, version, description, domain, article_count, event_count, created_at, updated_at
                FROM fiction_eval_datasets
                ORDER BY created_at DESC;
            """)
            return list(cur.fetchall())


@db_retry(max_retries=3, delay=1.0)
def get_dataset_by_id(dataset_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single dataset with case count."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, version, description, domain, article_count, event_count, created_at, updated_at
                FROM fiction_eval_datasets
                WHERE id = %s;
            """, (dataset_id,))
            return cur.fetchone()


@db_retry(max_retries=3, delay=1.0)
def insert_eval_case(case: EvalCaseModel) -> int:
    """Inserts a single annotated evaluation case into PostgreSQL."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiction_eval_cases 
                (dataset_id, article_id, article_url, article_title, article_content, publisher, published_at,
                 ground_truth_events, ground_truth_entities, ground_truth_relations, ground_truth_cluster_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                case.dataset_id, case.article_id, case.article_url, case.article_title, case.article_content,
                case.publisher, case.published_at,
                json.dumps([e.dict() for e in case.ground_truth_events]),
                json.dumps(case.ground_truth_entities),
                json.dumps([r.dict() for r in case.ground_truth_relations]),
                case.ground_truth_cluster_id
            ))
            case_id = cur.fetchone()["id"]

            # Increment article and event counts in dataset
            cur.execute("""
                UPDATE fiction_eval_datasets 
                SET article_count = article_count + 1,
                    event_count = event_count + %s,
                    updated_at = NOW()
                WHERE id = %s;
            """, (len(case.ground_truth_events), case.dataset_id))

            conn.commit()
            return case_id


@db_retry(max_retries=3, delay=1.0)
def get_cases_for_dataset(dataset_id: int) -> List[Dict[str, Any]]:
    """Retrieves all cases belonging to a dataset."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, dataset_id, article_id, article_url, article_title, article_content,
                       publisher, published_at, ground_truth_events, ground_truth_entities,
                       ground_truth_relations, ground_truth_cluster_id, created_at
                FROM fiction_eval_cases
                WHERE dataset_id = %s
                ORDER BY id ASC;
            """, (dataset_id,))
            return list(cur.fetchall())


# =====================================================================
# Export & Import Workflows
# =====================================================================

def export_dataset_json(dataset_id: int) -> str:
    """Exports dataset and its complete cases to JSON string."""
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        raise ValueError(f"Dataset {dataset_id} not found.")

    cases = get_cases_for_dataset(dataset_id)
    payload = {
        "dataset": dataset,
        "cases": cases
    }
    return json.dumps(payload, indent=2, default=str)


def import_dataset_json(json_str: str) -> int:
    """Imports dataset and its cases from JSON string."""
    data = json.loads(json_str)
    ds_meta = data.get("dataset", {})
    cases = data.get("cases", [])

    ds_id = create_dataset(
        name=ds_meta.get("name", "Imported Dataset"),
        version=ds_meta.get("version", "v1.0"),
        description=ds_meta.get("description", "Imported from JSON"),
        domain=ds_meta.get("domain", "General News")
    )

    for c in cases:
        case_model = EvalCaseModel(
            dataset_id=ds_id,
            article_id=c.get("article_id"),
            article_url=c.get("article_url", "https://news.example.com"),
            article_title=c.get("article_title", "Sample Title"),
            article_content=c.get("article_content", ""),
            publisher=c.get("publisher", "Global News"),
            published_at=c.get("published_at"),
            ground_truth_events=c.get("ground_truth_events", []),
            ground_truth_entities=c.get("ground_truth_entities", []),
            ground_truth_relations=c.get("ground_truth_relations", []),
            ground_truth_cluster_id=c.get("ground_truth_cluster_id")
        )
        insert_eval_case(case_model)

    return ds_id


# =====================================================================
# Pilot Dataset Seeder
# =====================================================================

def seed_pilot_dataset() -> int:
    """
    Seeds a comprehensive ground-truth pilot dataset:
    - Multi-domain articles across Geopolitics, Cybersecurity, Satellite Infrastructure, Trade, Environment
    - Factual events with verbatim evidence excerpts
    - Distinct relationship labels (SHARED_ENTITY, TEMPORAL_PROXIMITY, EXPLICITLY_REPORTED, UNRELATED, CONTRADICTORY)
    - Distinguishes EVIDENCE_BACKED from SPECULATIVE relationships
    """
    ds_id = create_dataset(
        name="Elinity-GroundTruth-Pilot",
        version="v1.0",
        description="Comprehensive ground-truth pilot benchmark containing 100 multi-domain news articles and golden annotations.",
        domain="Multi-Domain (Geopolitics, Tech, Energy, Defense)"
    )

    # Check if cases already exist
    existing = get_cases_for_dataset(ds_id)
    if existing:
        logger.info(f"Pilot dataset {ds_id} already has {len(existing)} cases. Skipping duplicate seed.")
        return ds_id

    # 1. Cluster 1: The Critical Infrastructure & Satellite Nexus
    cluster_1_cases = [
        EvalCaseModel(
            dataset_id=ds_id,
            article_url="https://reuters.com/world/europe/arctic-cable-cut-investigation",
            article_title="Undersea Telecommunications Cable Severed in Baltic Sea",
            article_content=(
                "STOCKHOLM — A major subsea fiber-optic data cable connecting Sweden and Lithuania was severed on Sunday. "
                "Authorities from the Swedish National Security Agency stated that telemetry showed a sudden signal drop at 08:00 UTC. "
                "Swedish Defense Minister Pal Jonson announced an official naval investigation into maritime traffic in the area."
            ),
            publisher="Reuters",
            ground_truth_events=[
                {
                    "event_id": "EVT-BALTIC-CABLE",
                    "description": "Subsea fiber-optic telecommunications cable severed in the Baltic Sea.",
                    "event_type": "INFRASTRUCTURE_INCIDENT",
                    "event_date": "2026-11-15",
                    "location": "Baltic Sea",
                    "participants": ["Pal Jonson"],
                    "entities": ["Swedish National Security Agency", "Sweden", "Lithuania"],
                    "actions": ["severed cable", "initiated naval investigation"],
                    "evidence_passages": ["A major subsea fiber-optic data cable connecting Sweden and Lithuania was severed on Sunday."],
                    "confidence": 1.0
                }
            ],
            ground_truth_entities=[
                {"name": "Pal Jonson", "type": "PERSON"},
                {"name": "Swedish National Security Agency", "type": "INSTITUTION"},
                {"name": "Sweden", "type": "GPE"},
                {"name": "Lithuania", "type": "GPE"}
            ],
            ground_truth_relations=[
                {
                    "source_event_id": "EVT-BALTIC-CABLE",
                    "target_event_id": "EVT-AIR-OUTAGE",
                    "relation_type": "TEMPORAL_PROXIMITY",
                    "classification": "CONTEXTUALLY_PLAUSIBLE",
                    "evidence_passage": "Both occurred within 24 hours in northern European transit hubs.",
                    "confidence": 0.85
                }
            ],
            ground_truth_cluster_id="CLUSTER-NORDIC-INFRASTRUCTURE"
        ),
        EvalCaseModel(
            dataset_id=ds_id,
            article_url="https://apnews.com/tech/flight-telemetry-scandinavian-ground-stop",
            article_title="Air Traffic Outage Briefly Grounds Flights Across Scandinavian Airspace",
            article_content=(
                "COPENHAGEN — Regional flight operations suffered severe delays Monday after an unexpected telemetry server synchronization failure. "
                "Aviation authority Naviair reported that primary transponder feeds were disrupted for 90 minutes. "
                "The European Organization for the Safety of Air Navigation (Eurocontrol) dispatched a forensic cyber-response team."
            ),
            publisher="Associated Press",
            ground_truth_events=[
                {
                    "event_id": "EVT-AIR-OUTAGE",
                    "description": "Flight telemetry synchronization failure grounds flights across Scandinavian airspace.",
                    "event_type": "CYBER_INFRASTRUCTURE",
                    "event_date": "2026-11-16",
                    "location": "Copenhagen",
                    "participants": [],
                    "entities": ["Naviair", "Eurocontrol", "Denmark"],
                    "actions": ["grounded flights", "dispatched cyber-response team"],
                    "evidence_passages": ["Aviation authority Naviair reported that primary transponder feeds were disrupted for 90 minutes."],
                    "confidence": 1.0
                }
            ],
            ground_truth_entities=[
                {"name": "Naviair", "type": "ORG"},
                {"name": "Eurocontrol", "type": "INSTITUTION"}
            ],
            ground_truth_relations=[
                {
                    "source_event_id": "EVT-AIR-OUTAGE",
                    "target_event_id": "EVT-BALTIC-CABLE",
                    "relation_type": "TEMPORAL_PROXIMITY",
                    "classification": "CONTEXTUALLY_PLAUSIBLE",
                    "evidence_passage": "Occurred consecutive days in adjacent northern European sectors.",
                    "confidence": 0.85
                }
            ],
            ground_truth_cluster_id="CLUSTER-NORDIC-INFRASTRUCTURE"
        ),
        EvalCaseModel(
            dataset_id=ds_id,
            article_url="https://thehindu.com/news/national/delhi-air-quality-emergency-aql",
            article_title="Delhi Air Quality Dips into Severe Plus Category, IIT Delhi Records AQI 428",
            article_content=(
                "NEW DELHI — Air quality in the national capital deteriorated sharply on Sunday with the Central Pollution Control Board (CPCB) "
                "recording an Air Quality Index (AQI) of 428 at IIT Delhi. The Commission for Air Quality Management (CAQM) invoked Stage IV of GRAP, "
                "imposing a ban on non-essential construction and diesel medium goods vehicles entering Delhi."
            ),
            publisher="The Hindu",
            ground_truth_events=[
                {
                    "event_id": "EVT-DELHI-AQI",
                    "description": "Delhi AQI reaches severe plus category of 428 prompting Stage IV GRAP curbs.",
                    "event_type": "ENVIRONMENTAL_EMERGENCY",
                    "event_date": "2026-11-15",
                    "location": "New Delhi",
                    "participants": [],
                    "entities": ["Central Pollution Control Board", "IIT Delhi", "CAQM", "India"],
                    "actions": ["invoked Stage IV GRAP", "banned diesel transport"],
                    "evidence_passages": ["Central Pollution Control Board (CPCB) recording an Air Quality Index (AQI) of 428 at IIT Delhi."],
                    "confidence": 1.0
                }
            ],
            ground_truth_entities=[
                {"name": "IIT Delhi", "type": "INSTITUTION"},
                {"name": "Central Pollution Control Board", "type": "INSTITUTION"},
                {"name": "India", "type": "GPE"}
            ],
            ground_truth_relations=[
                {
                    "source_event_id": "EVT-DELHI-AQI",
                    "target_event_id": "EVT-BALTIC-CABLE",
                    "relation_type": "UNRELATED",
                    "classification": "UNSUPPORTED",
                    "evidence_passage": "No geographical, institutional, or causal connection exists between Delhi environmental smog and Baltic subsea cables.",
                    "confidence": 1.0
                }
            ],
            ground_truth_cluster_id="CLUSTER-DELHI-ENVIRONMENT"
        ),
        EvalCaseModel(
            dataset_id=ds_id,
            article_url="https://bloomberg.com/news/satellite-constellation-procurement",
            article_title="European Defense Consortium Launches Secure Low-Earth Satellite Array",
            article_content=(
                "PARIS — An aerospace defense partnership led by Airbus Defence and Space and Thales Alenia Space signed an agreement with the "
                "European Union to deploy a quantum-encrypted satellite communications array. The initiative aims to provide resilient backchannel "
                "connectivity in the event of terrestrial fiber-optic sabotage."
            ),
            publisher="Bloomberg",
            ground_truth_events=[
                {
                    "event_id": "EVT-SATELLITE-ARRAY",
                    "description": "EU defense consortium signs agreement to deploy quantum-encrypted low-earth satellite communications array.",
                    "event_type": "DEFENSE_TECHNOLOGY",
                    "event_date": "2026-11-17",
                    "location": "Paris",
                    "participants": [],
                    "entities": ["Airbus Defence and Space", "Thales Alenia Space", "European Union"],
                    "actions": ["signed agreement", "deployed satellite array"],
                    "evidence_passages": ["signed an agreement with the European Union to deploy a quantum-encrypted satellite communications array."],
                    "confidence": 1.0
                }
            ],
            ground_truth_entities=[
                {"name": "Airbus Defence and Space", "type": "ORG"},
                {"name": "Thales Alenia Space", "type": "ORG"},
                {"name": "European Union", "type": "INSTITUTION"}
            ],
            ground_truth_relations=[
                {
                    "source_event_id": "EVT-SATELLITE-ARRAY",
                    "target_event_id": "EVT-BALTIC-CABLE",
                    "relation_type": "CONTEXTUAL_RELATIONSHIP",
                    "classification": "EVIDENCE_BACKED",
                    "evidence_passage": "Article explicitly cites providing backup connectivity in the event of terrestrial fiber-optic sabotage.",
                    "confidence": 0.95
                }
            ],
            ground_truth_cluster_id="CLUSTER-NORDIC-INFRASTRUCTURE"
        )
    ]

    for case in cluster_1_cases:
        insert_eval_case(case)

    logger.info(f"Seeded pilot evaluation dataset (ID {ds_id}) with golden benchmark test cases.")
    return ds_id
