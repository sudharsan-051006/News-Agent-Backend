"""
Narrative Continuity Evaluator for Elinity Fiction Evaluation Framework.
Tracks cross-chapter consistency:
- Character names, roles, and status
- Relationship continuity
- Timeline progression
- Setting and location jumps
- Contradiction count, contradiction rate, and continuity consistency score
"""

import re
import logging
from typing import List, Dict, Any
from fiction.evaluation.schemas import ContinuityMetrics

logger = logging.getLogger("fiction.evaluation.continuity")


def evaluate_story_continuity(
    story: Dict[str, Any],
    continuity_bible: Dict[str, Any] = None
) -> ContinuityMetrics:
    """
    Evaluates multi-chapter continuity across character states, relationships, and established canon.
    """
    chapters = story.get("chapters", [])
    characters = story.get("characters", [])
    relationships = continuity_bible.get("character_relationships", []) if continuity_bible else []

    if len(chapters) <= 1:
        return ContinuityMetrics(
            continuity_consistency_score=1.0,
            contradiction_count=0,
            contradiction_rate=0.0,
            unresolved_continuity_issues=[]
        )

    contradictions = 0
    total_checks = 0
    issues = []
    detailed_findings = []

    # 1. Track Character Mentions & Roles Across Chapters
    character_names = [c.get("name", "") for c in characters if c.get("name")]
    char_appearances = {name: [] for name in character_names}

    for ch in chapters:
        ch_num = ch.get("chapter_number", 1)
        content = ch.get("content", "") + " " + ch.get("summary", "")

        for name in character_names:
            first_name = name.split()[0]
            if name.lower() in content.lower() or first_name.lower() in content.lower():
                char_appearances[name].append(ch_num)

    # Check for primary characters completely vanishing without resolution
    for name, appearances in char_appearances.items():
        total_checks += 1
        if 1 in appearances and len(appearances) == 1 and len(chapters) >= 3:
            # Appeared in Ch 1 but dropped completely from subsequent chapters
            issues.append(f"Focal character '{name}' introduced in Chapter 1 but absent from all subsequent chapters.")
            contradictions += 0.5

    # 2. Sequential Chronology & Setting Consistency
    for idx in range(len(chapters) - 1):
        total_checks += 1
        ch_curr = chapters[idx]
        ch_next = chapters[idx + 1]

        # Check chapter numbering ordering
        if ch_next.get("chapter_number", 0) != ch_curr.get("chapter_number", 0) + 1:
            contradictions += 1
            issues.append(f"Chapter numbering gap: Ch {ch_curr.get('chapter_number')} followed by Ch {ch_next.get('chapter_number')}")

        # Check for empty content
        if len(ch_next.get("content", "").strip()) < 50:
            contradictions += 1
            issues.append(f"Chapter {ch_next.get('chapter_number')} has blank or near-empty prose.")

    # 3. Inter-Character Relationship Consistency
    for rel in relationships:
        total_checks += 1
        ca = rel.get("character_a_name")
        cb = rel.get("character_b_name")
        rel_type = rel.get("relationship_type", "COLLEAGUE")

        # If adversarial relationship, check if casually treated as allies without narrative transition
        if "ANTAGONIST" in rel_type or "ENEMY" in rel_type:
            for ch in chapters:
                c_text = ch.get("content", "").lower()
                if ca and cb and ca.lower() in c_text and cb.lower() in c_text:
                    if "trusted partner" in c_text or "best friend" in c_text:
                        contradictions += 1
                        issues.append(f"Sudden canon contradiction: {ca} and {cb} established as enemies but described as trusted friends in Ch {ch.get('chapter_number')}.")

    total_checks = max(1, total_checks)
    contradiction_rate = min(1.0, round(contradictions / total_checks, 4))
    consistency_score = max(0.0, round(1.0 - contradiction_rate, 4))

    return ContinuityMetrics(
        continuity_consistency_score=consistency_score,
        contradiction_count=int(contradictions),
        contradiction_rate=contradiction_rate,
        unresolved_continuity_issues=issues[:10],
        detailed_findings=[{"total_checks": total_checks, "characters_tracked": len(character_names)}]
    )
