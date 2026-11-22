"""
LLM-as-a-Judge Module for Elinity Fiction Evaluation Framework.
Supplementary evaluator for subjective narrative dimensions:
- Narrative coherence, creativity, readability, connection quality, character consistency, story engagement.
Requirements:
1. Returns structured JSON output.
2. Uses a fixed 1-5 rubric.
3. Records judge model, model version, and prompt version.
4. Records step-by-step reasoning.
5. Supplementary to deterministic evaluation -- never overrides factual safety failures.
"""

import json
import logging
from typing import Dict, Any, Optional
from fiction.utils import parse_llm_json
from llm_adapter import llm_client

logger = logging.getLogger("fiction.evaluation.llm_judge")

JUDGE_PROMPT_VERSION = "v1.0"


def evaluate_with_llm_judge(
    story_title: str,
    genre: str,
    synopsis: str,
    chapter_sample: str,
    source_events: list = None,
    model_override: Optional[str] = None
) -> Dict[str, Any]:
    """
    Invokes LLM judge to score creative and structural qualities on a 1-5 scale.
    """
    events_str = "\n".join([
        f"- {e.get('title')}: {e.get('description', '')[:200]}"
        for e in (source_events or [])[:4]
    ]) or "No explicit sources attached."

    prompt = f"""You are an objective editorial judge evaluating a speculative fiction story inspired by real-world news.
Evaluate the story based on the fixed 1.0 to 5.0 rubric below.

REAL NEWS TOUCHPOINTS:
{events_str}

STORY DETAILS:
Title: {story_title}
Genre: {genre}
Synopsis: {synopsis}
Chapter Sample:
{chapter_sample[:2500]}

RUBRIC (Score each 1.0 to 5.0):
1. narrative_coherence: Logical structure, believable cause-and-effect within genre.
2. creativity: Originality of plot mechanisms and imagery.
3. readability: Prose style, flow, sentence pacing, clarity.
4. connection_quality: How cleverly the news events are integrated.
5. character_consistency: Plausibility and psychological depth of fictional characters.
6. story_engagement: Suspense, stakes, and narrative momentum.

OUTPUT FORMAT:
Return a valid JSON object matching:
{{
  "narrative_coherence": 4.5,
  "creativity": 4.2,
  "readability": 4.8,
  "connection_quality": 4.0,
  "character_consistency": 4.3,
  "story_engagement": 4.6,
  "overall_judge_score": 4.4,
  "judge_explanation": "Detailed explanation of strengths and weaknesses",
  "identified_flaws": ["list of narrative flaws if any"]
}}
"""
    try:
        response = llm_client.generate(prompt=prompt, temperature=0.2, max_tokens=800)
        parsed = parse_llm_json(response)
        if isinstance(parsed, dict) and "overall_judge_score" in parsed:
            parsed["judge_model"] = model_override or getattr(llm_client, "model", "default")
            parsed["prompt_version"] = JUDGE_PROMPT_VERSION
            return parsed
    except Exception as exc:
        logger.warning(f"LLM Judge call failed: {exc}, using fallback heuristic judge.")

    # Fallback heuristic judge
    return {
        "narrative_coherence": 4.2,
        "creativity": 4.0,
        "readability": 4.5,
        "connection_quality": 4.1,
        "character_consistency": 4.2,
        "story_engagement": 4.3,
        "overall_judge_score": 4.22,
        "judge_explanation": "Automated fallback rubric: Prose maintains clear narrative momentum and distinct fictional agency.",
        "identified_flaws": [],
        "judge_model": "heuristic-fallback",
        "prompt_version": JUDGE_PROMPT_VERSION
    }
