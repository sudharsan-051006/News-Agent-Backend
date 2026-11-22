"""
Pydantic Schemas and Data Models for Elinity News-to-Fiction Engine.
Provides strict validation, serialization, and typing across the pipeline.
"""

from typing import List, Optional, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, Field


# =====================================================================
# 1. Events & Provenance
# =====================================================================

class EventSourceModel(BaseModel):
    article_id: Optional[int] = None
    source_url: str
    evidence_excerpt: str
    publisher: Optional[str] = "Unknown Source"
    published_at: Optional[datetime] = None


class ExtractedEvent(BaseModel):
    event_type: str = Field(description="Specific categorization of event e.g. DIPLOMATIC_MEETING, CYBER_BREACH, SATELLITE_LAUNCH")
    title: str = Field(description="Concise factual headline of the real-world event")
    description: str = Field(description="2-3 sentence objective description of what occurred")
    main_action: str = Field(description="Core verb or primary action e.g. signed agreement, launched rocket, filed lawsuit")
    event_date: Optional[date] = Field(default=None, description="Date event took place, if distinct from publication date")
    date_precision: str = Field(default="EXACT", description="EXACT, APPROXIMATE, MONTH, YEAR, UNKNOWN")
    location: Optional[str] = Field(default=None, description="City, region, or specific site")
    country: Optional[str] = Field(default=None, description="Primary nation or global")
    participants: List[str] = Field(default_factory=list, description="Key named individuals")
    organizations: List[str] = Field(default_factory=list, description="Companies, NGOs, military bodies")
    government_entities: List[str] = Field(default_factory=list, description="Ministries, departments, state bodies")
    topics: List[str] = Field(default_factory=list, description="Key domain topics e.g. technology, geopolitics, defense")
    evidence_excerpts: List[str] = Field(default_factory=list, description="Direct verbatim excerpts from article proving this event")
    extraction_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class EventExtractionBatch(BaseModel):
    events: List[ExtractedEvent] = Field(default_factory=list)


# =====================================================================
# 2. Entity Resolution
# =====================================================================

class EntityResolution(BaseModel):
    canonical_name: str
    entity_type: str  # PERSON, ORG, GPE, LOCATION, INSTITUTION
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    role: str = "PARTICIPANT"


# =====================================================================
# 3. Relationship Discovery
# =====================================================================

class EventRelationModel(BaseModel):
    source_event_id: int
    target_event_id: int
    relation_type: str  # SHARED_ENTITY, TEMPORAL_PROXIMITY, SEMANTIC_SIMILARITY, CROSS_DOMAIN, SOURCE_REPORTED_CAUSAL_LINK, CONTRADICTION
    is_verified: bool = False
    confidence: float = 0.5
    evidence_text: str = ""
    shared_entity_name: Optional[str] = None


# =====================================================================
# 4. Event Clusters
# =====================================================================

class EventClusterModel(BaseModel):
    cluster_code: str
    name: str
    theme: str
    summary: str
    domains: List[str] = Field(default_factory=list)
    event_ids: List[int] = Field(default_factory=list)


# =====================================================================
# 5. Fictional Scenarios & Evaluation
# =====================================================================

class FictionalScenarioModel(BaseModel):
    title: str = Field(description="Compelling fictional story title")
    genre: str = Field(description="Specific genre e.g. Political Thriller, Technological Espionage, Sci-Fi Mystery")
    logline: str = Field(description="Single-sentence dramatic hook")
    premise: str = Field(description="2-3 paragraph premise connecting the events narratively")
    source_event_ids: List[int] = Field(default_factory=list)
    verified_facts: List[str] = Field(default_factory=list, description="Facts verified from underlying real news")
    unverified_observations: List[str] = Field(default_factory=list, description="Curious coincidences or unverified reports")
    fictional_assumptions: List[str] = Field(default_factory=list, description="Explicit fictional inventions made for storytelling")
    fictional_characters: List[Dict[str, str]] = Field(default_factory=list, description="Invented characters e.g. name, role, motivation")
    central_conflict: str = Field(description="Core tension driving the narrative")
    possible_antagonist: Optional[str] = Field(default=None, description="Fictional antagonist or opposing force")
    narrative_stakes: str = Field(description="What happens if the protagonist fails")
    potential_twists: List[str] = Field(default_factory=list, description="Surprising narrative turns")
    disclaimer: str = Field(
        default="This is a fictional story inspired by real-world news events. The narrative connections, characters, motives, and developments are invented and do not imply that the underlying news events are causally related."
    )


class ScenarioEvaluationScores(BaseModel):
    event_coverage: float = Field(ge=0, le=10, description="How meaningfully all cluster events are utilized")
    narrative_coherence: float = Field(ge=0, le=10, description="Logical consistency of the plot premise")
    originality: float = Field(ge=0, le=10, description="Creative departure from generic tropes")
    genre_suitability: float = Field(ge=0, le=10, description="Faithfulness to chosen genre conventions")
    diversity: float = Field(ge=0, le=10, description="Distinctiveness from other candidate premises")
    source_traceability: float = Field(ge=0, le=10, description="Clear provenance back to real news")
    fact_fiction_separation: float = Field(ge=0, le=10, description="Zero defamatory or misleading factual claims")
    total_score: float = Field(ge=0, le=10)
    feedback: str = ""
    is_approved: bool = True


# =====================================================================
# 6. Story Architecture & Chapters
# =====================================================================

class CharacterBlueprint(BaseModel):
    name: str
    role: str  # PROTAGONIST, ANTAGONIST, ALLY, MENTOR, INVESTIGATOR
    description: str
    motivations: str
    is_fictional: bool = True


class CharacterRelationBlueprint(BaseModel):
    character_a: str
    character_b: str
    relationship_type: str
    description: str


class ChapterPlan(BaseModel):
    chapter_number: int
    title: str
    summary: str
    focal_character: str
    key_revelations: List[str] = Field(default_factory=list)


class StoryArchitecturePlan(BaseModel):
    title: str
    genre: str
    synopsis: str
    world_setting: str
    central_conflict: str
    ending_plan: str
    characters: List[CharacterBlueprint] = Field(default_factory=list)
    relationships: List[CharacterRelationBlueprint] = Field(default_factory=list)
    chapters: List[ChapterPlan] = Field(default_factory=list)
    disclaimer: str = (
        "This is a fictional story inspired by real-world news events. The narrative connections, characters, motives, and developments are invented and do not imply that the underlying news events are causally related."
    )


class ChapterGenerationResult(BaseModel):
    story_id: int
    chapter_number: int
    title: str
    content: str
    summary: str
    word_count: int


# =====================================================================
# 7. Continuity Tracking
# =====================================================================

class ContinuityState(BaseModel):
    story_id: int
    active_characters: List[Dict[str, Any]] = Field(default_factory=list)
    character_relationships: List[Dict[str, Any]] = Field(default_factory=list)
    timeline_events: List[Dict[str, Any]] = Field(default_factory=list)
    unresolved_mysteries: List[str] = Field(default_factory=list)
    previous_chapter_summaries: List[Dict[str, Any]] = Field(default_factory=list)


# =====================================================================
# 8. Background Job Tracking
# =====================================================================

class JobStatusResponse(BaseModel):
    job_id: int
    job_type: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED
    progress_pct: int
    current_stage: str
    result_summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
