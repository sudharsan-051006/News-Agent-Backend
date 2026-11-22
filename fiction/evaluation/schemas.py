"""
Pydantic Schemas for Elinity Fiction Evaluation Framework.
Provides strict validation for datasets, annotations, component metrics,
human ratings, benchmarks, and release gating criteria.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


# =====================================================================
# 1. Dataset & Case Schemas
# =====================================================================

class GroundTruthEvent(BaseModel):
    event_id: str
    description: str
    event_type: str
    event_date: Optional[str] = None
    location: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)
    evidence_passages: List[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundTruthRelation(BaseModel):
    source_event_id: str
    target_event_id: str
    relation_type: str  # EXPLICITLY_REPORTED_RELATIONSHIP, SHARED_ENTITY, TEMPORAL_PROXIMITY, SEMANTIC_SIMILARITY, CONTEXTUAL_RELATIONSHIP, UNRELATED, CONTRADICTORY
    classification: str  # EVIDENCE_BACKED, CONTEXTUALLY_PLAUSIBLE, SPECULATIVE, UNSUPPORTED
    evidence_passage: Optional[str] = None
    confidence: float = 1.0


class EvalCaseModel(BaseModel):
    id: Optional[int] = None
    dataset_id: Optional[int] = None
    article_id: Optional[int] = None
    article_url: str
    article_title: str
    article_content: str
    publisher: Optional[str] = "Global News"
    published_at: Optional[datetime] = None
    ground_truth_events: List[GroundTruthEvent] = Field(default_factory=list)
    ground_truth_entities: List[Dict[str, Any]] = Field(default_factory=list)
    ground_truth_relations: List[GroundTruthRelation] = Field(default_factory=list)
    ground_truth_cluster_id: Optional[str] = None


class DatasetMetadata(BaseModel):
    id: Optional[int] = None
    name: str
    version: str = "v1.0"
    description: Optional[str] = None
    domain: str = "General News"
    article_count: int = 0
    event_count: int = 0
    created_at: Optional[datetime] = None


# =====================================================================
# 2. Component Evaluation Metric Schemas
# =====================================================================

class EventExtractionMetrics(BaseModel):
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    type_accuracy: float = Field(ge=0.0, le=1.0)
    date_accuracy: float = Field(ge=0.0, le=1.0)
    entity_accuracy: float = Field(ge=0.0, le=1.0)
    evidence_accuracy: float = Field(ge=0.0, le=1.0)
    matched_events_count: int = 0
    total_predicted: int = 0
    total_ground_truth: int = 0
    error_breakdown: Dict[str, Any] = Field(default_factory=dict)


class EntityResolutionMetrics(BaseModel):
    entity_linking_accuracy: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    false_merge_rate: float = Field(ge=0.0, le=1.0)
    false_split_rate: float = Field(ge=0.0, le=1.0)
    errors: List[Dict[str, Any]] = Field(default_factory=list)


class RelationshipMetrics(BaseModel):
    precision_at_k: float = Field(ge=0.0, le=1.0)
    recall_at_k: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    evidence_support_rate: float = Field(ge=0.0, le=1.0)
    unsupported_relationship_rate: float = Field(ge=0.0, le=1.0)
    relationship_type_accuracy: float = Field(ge=0.0, le=1.0)
    false_causal_relationship_rate: float = Field(ge=0.0, le=1.0)
    confusion_matrix: Dict[str, Any] = Field(default_factory=dict)
    unsupported_claims: List[Dict[str, Any]] = Field(default_factory=list)


class ClusteringMetrics(BaseModel):
    bcubed_precision: float = Field(ge=0.0, le=1.0)
    bcubed_recall: float = Field(ge=0.0, le=1.0)
    bcubed_f1: float = Field(ge=0.0, le=1.0)
    cluster_purity: float = Field(ge=0.0, le=1.0)
    cluster_completeness: float = Field(ge=0.0, le=1.0)
    duplicate_events_detected: int = 0
    overlapping_events_detected: int = 0
    cluster_error_report: List[Dict[str, Any]] = Field(default_factory=list)


class ScenarioEvaluationRubric(BaseModel):
    event_coverage: float = Field(ge=1.0, le=5.0)
    connection_quality: float = Field(ge=1.0, le=5.0)
    narrative_coherence: float = Field(ge=1.0, le=5.0)
    creativity: float = Field(ge=1.0, le=5.0)
    originality: float = Field(ge=1.0, le=5.0)
    genre_suitability: float = Field(ge=1.0, le=5.0)
    plausibility: float = Field(ge=1.0, le=5.0)
    fact_fiction_separation: float = Field(ge=1.0, le=5.0)
    overall_score: float = Field(ge=1.0, le=5.0)
    feedback: str = ""


class HumanReviewModel(BaseModel):
    reviewer_name: str
    ratings: Dict[str, float] = Field(
        description="1-5 scale scores: news_grounding, connection_quality, creativity, coherence, readability, engagement, character_quality, pacing, continuity, fiction_transparency"
    )
    overall_score: float = Field(ge=1.0, le=5.0)
    comments: Optional[str] = None
    factuality_issues: List[str] = Field(default_factory=list)
    is_critical_issue: bool = False
    inter_rater_group_id: Optional[str] = None


class ContinuityMetrics(BaseModel):
    continuity_consistency_score: float = Field(ge=0.0, le=1.0)
    contradiction_count: int = 0
    contradiction_rate: float = Field(ge=0.0, le=1.0)
    unresolved_continuity_issues: List[str] = Field(default_factory=list)
    detailed_findings: List[Dict[str, Any]] = Field(default_factory=list)


class FactualitySafetyMetrics(BaseModel):
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    source_attribution_accuracy: float = Field(ge=0.0, le=1.0)
    fiction_fact_classification_accuracy: float = Field(ge=0.0, le=1.0)
    critical_factual_misrepresentations: int = 0
    has_mandatory_disclaimer: bool = True
    release_gate_passed: bool = True
    critical_violations: List[str] = Field(default_factory=list)


# =====================================================================
# 3. Performance, Benchmark & Run Summaries
# =====================================================================

class PerformanceMetrics(BaseModel):
    total_execution_time_seconds: float
    time_per_component: Dict[str, float] = Field(default_factory=dict)
    average_article_processing_time: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    retry_count: int = 0
    estimated_cost_usd: Optional[float] = None
    pricing_status: str = "ESTIMATED"  # 'ESTIMATED', 'EXACT', 'UNKNOWN'


class BenchmarkComparisonModel(BaseModel):
    comparison_type: str  # 'BASELINE', 'ABLATION'
    system_variant: str  # 'BASELINE_A_DIRECT_LLM', 'BASELINE_B_SEMANTIC', 'BASELINE_C_STRUCTURED', 'BASELINE_D_FULL_ELINITY'
    metrics: Dict[str, float]
    cost_tokens: int = 0
    execution_time_seconds: float = 0.0


class EvaluationRunSummary(BaseModel):
    run_id: int
    run_code: str
    dataset_name: str
    run_type: str
    model_provider: str
    model_name: str
    prompt_version: str
    status: str
    release_gate_passed: bool
    summary_scores: Dict[str, float] = Field(default_factory=dict)
    critical_violations: List[str] = Field(default_factory=list)
    execution_time_seconds: float = 0.0
    token_usage: int = 0
    estimated_cost_usd: Optional[float] = None
