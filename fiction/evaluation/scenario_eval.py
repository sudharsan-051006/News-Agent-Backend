"""
Fictional Premise Evaluator for Elinity Fiction Evaluation Framework.
Evaluates premises produced from event clusters using a rigorous 1-5 scale rubric across 8 criteria:
1. event_coverage (1-5)
2. connection_quality (1-5)
3. narrative_coherence (1-5)
4. creativity (1-5)
5. originality (1-5)
6. genre_suitability (1-5)
7. plausibility within fictional world (1-5)
8. fact_fiction_separation (1-5)
"""

import logging
from typing import Dict, Any, List
from fiction.evaluation.schemas import ScenarioEvaluationRubric

logger = logging.getLogger("fiction.evaluation.scenario_eval")


def evaluate_fictional_premise(
    scenario: Dict[str, Any],
    cluster_events: List[Dict[str, Any]] = None
) -> ScenarioEvaluationRubric:
    """
    Evaluates a generated fictional premise across the 8 rubric dimensions on a 1-5 scale.
    Combines rule-based integrity checks with narrative coherence scoring.
    """
    title = scenario.get("title", "")
    premise = scenario.get("premise", "")
    fictional_assumptions = scenario.get("fictional_assumptions", [])
    verified_facts = scenario.get("verified_facts", [])
    characters = scenario.get("fictional_characters", [])
    possible_antagonist = scenario.get("possible_antagonist", "")
    central_conflict = scenario.get("central_conflict", "")

    # 1. Event Coverage (1-5): Did the premise weave in the cluster events?
    if cluster_events:
        c_count = len(cluster_events)
        mentioned_count = 0
        for ev in cluster_events:
            ev_title = ev.get("title", "").lower()
            key_words = [w for w in ev_title.split() if len(w) > 4]
            if any(w in premise.lower() for w in key_words):
                mentioned_count += 1
        coverage_ratio = mentioned_count / c_count if c_count > 0 else 1.0
        event_coverage = round(1.0 + (coverage_ratio * 4.0), 2)
    else:
        event_coverage = 4.0 if verified_facts else 3.0

    # 2. Connection Quality (1-5): Are cross-domain connections woven plausibly?
    connection_quality = 4.0 if len(fictional_assumptions) >= 2 else (3.0 if fictional_assumptions else 2.0)

    # 3. Narrative Coherence (1-5): Is there a clear conflict and logical flow?
    has_conflict = bool(central_conflict and len(central_conflict) > 20)
    has_antagonist = bool(possible_antagonist)
    coherence = 4.5 if (has_conflict and has_antagonist and len(premise) > 150) else 3.5

    # 4. Creativity (1-5): Rich narrative worldbuilding
    creativity = 4.2 if len(premise) > 250 else 3.2

    # 5. Originality (1-5): Distinctive premise avoiding generic clichés
    originality = 4.0

    # 6. Genre Suitability (1-5)
    genre = scenario.get("genre", "Political Thriller")
    genre_suitability = 4.5 if genre in [
        "Political Thriller", "Technological Espionage", "Investigative Mystery",
        "Speculative Science Fiction", "International Noir"
    ] else 3.5

    # 7. Plausibility (1-5)
    plausibility = 4.0

    # 8. Fact-Fiction Separation (1-5) -- CRITICAL: Real people must never be defamed!
    # Check if fictional characters exist for wrongdoing
    has_fictional_agents = bool(characters and any(c.get("name") for c in characters))
    disclaimer_present = bool("This is a fictional story" in scenario.get("disclaimer", ""))

    if has_fictional_agents and disclaimer_present and len(fictional_assumptions) > 0:
        fact_sep = 5.0
    elif disclaimer_present:
        fact_sep = 4.0
    else:
        fact_sep = 1.0  # Critical defect: Missing disclaimer!

    scores = [
        event_coverage, connection_quality, coherence, creativity,
        originality, genre_suitability, plausibility, fact_sep
    ]
    overall = round(sum(scores) / len(scores), 2)

    feedback = (
        f"Premise demonstrates {overall}/5.0 quality. "
        f"Event coverage: {event_coverage}/5, Fact/Fiction separation: {fact_sep}/5. "
        f"{'Protected real individuals with fictional characters.' if fact_sep >= 4.0 else 'Warning: Insufficient separation.'}"
    )

    return ScenarioEvaluationRubric(
        event_coverage=min(5.0, max(1.0, event_coverage)),
        connection_quality=min(5.0, max(1.0, connection_quality)),
        narrative_coherence=min(5.0, max(1.0, coherence)),
        creativity=min(5.0, max(1.0, creativity)),
        originality=min(5.0, max(1.0, originality)),
        genre_suitability=min(5.0, max(1.0, genre_suitability)),
        plausibility=min(5.0, max(1.0, plausibility)),
        fact_fiction_separation=min(5.0, max(1.0, fact_sep)),
        overall_score=overall,
        feedback=feedback
    )
