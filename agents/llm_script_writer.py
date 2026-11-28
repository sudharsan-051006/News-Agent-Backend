"""LLM News Broadcast Script Writer for News-Agent-Backend.

Uses local Ollama (mistral:latest) to craft punchy, natural, conversational
broadcast television news anchor narration for audio synthesis.
Eliminates robotic repetition of category names and repetitive boilerplate.
"""
from __future__ import annotations

import os
import re
import time
import concurrent.futures
from typing import Any, Dict, List, Optional
import ollama

DEFAULT_OLLAMA_MODEL = "mistral:latest"
NUM_CORES = os.cpu_count() or 4


def generate_broadcast_intro(
    day_name: str,
    date_str: str,
    time_str: str,
    edition: str,
    total_count: int = 25,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> str:
    """Generate dynamic time-of-day intro greeting using local LLM."""
    prompt = (
        f"You are a professional TV news anchor for Elinity News. "
        f"Write a short, engaging 2-sentence opening greeting for today's {edition} news bulletin. "
        f"Details: Day is {day_name}, Date is {date_str}, Time is {time_str} IST, bringing top {total_count} headlines. "
        f"Must begin with 'Namaste and welcome'. Keep it under 35 words. Return only the spoken text."
    )
    try:
        res = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional TV news broadcast anchor. Write spoken audio narration."},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.4, "num_thread": NUM_CORES},
        )
        text = res["message"]["content"].strip().strip('"\'')
        if text and len(text) > 20:
            return text
    except Exception as exc:
        print(f"⚠️ Ollama intro generation fallback ({exc})")

    # High-quality dynamic fallback
    return (
        f"Namaste and welcome to today's {edition} news bulletin for {day_name}, {date_str}. "
        f"We bring you the top {total_count} headlines making news across the nation and around the world. Let us begin."
    )


def generate_broadcast_outro(
    day_name: str,
    date_str: str,
    total_count: int = 25,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> str:
    """Generate dynamic broadcast sign-off using local LLM."""
    prompt = (
        f"You are a professional TV news anchor. "
        f"Write a warm, concise 2-sentence sign-off for the end of today's top {total_count} headlines bulletin on {day_name}, {date_str}. "
        f"Mention scanning the on-screen QR codes or visiting the news portal for full reports. "
        f"End with 'Namaste'. Keep it under 35 words. Return only the spoken text."
    )
    try:
        res = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional TV news broadcast anchor. Write spoken audio narration."},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.4, "num_thread": NUM_CORES},
        )
        text = res["message"]["content"].strip().strip('"\'')
        if text and len(text) > 20:
            return text
    except Exception as exc:
        print(f"⚠️ Ollama outro generation fallback ({exc})")

    return (
        f"Those were today's top {total_count} headlines for {day_name}, {date_str}. "
        f"Scan the on-screen QR codes to read the full articles on our news portal. "
        f"Thank you for watching. Namaste and stay informed."
    )


def rewrite_story_for_broadcast(
    headline: str,
    summary: str,
    category: str = "General",
    index: int = 1,
    total: int = 25,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> str:
    """Rewrite a news headline and summary into 1-2 punchy spoken broadcast sentences."""
    clean_h = re.sub(r'[\r\n\t]+', ' ', headline).strip()
    clean_s = re.sub(r'[\r\n\t]+', ' ', summary).strip() if summary else ""

    prompt = (
        f"Rewrite this news story into 1 or 2 concise, conversational spoken sentences for a TV news anchor. "
        f"Do NOT say 'In tech today', 'In sports today', 'Breaking news', or mention category names. "
        f"Speak naturally like a prime-time news reader. Keep it between 18 and 32 words.\n\n"
        f"Headline: {clean_h}\n"
        f"Details: {clean_s[:220]}"
    )
    try:
        res = ollama.chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an experienced TV news anchor. Rewrite the supplied news story into crisp, "
                        "natural spoken broadcast English. Output ONLY the anchor narration sentence."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.3, "num_thread": NUM_CORES},
        )
        spoken = res["message"]["content"].strip().strip('"\'')
        spoken = re.sub(r'[\r\n]+', ' ', spoken).strip()
        # Ensure it starts clean and is reasonable length
        if 20 <= len(spoken) <= 320:
            return spoken
    except Exception as exc:
        pass

    # Graceful fallback to crisp journalistic prose if LLM unavailable
    if clean_s and len(clean_s) > 20:
        first_sentence = clean_s.split(". ")[0].strip()
        if not first_sentence.endswith("."):
            first_sentence += "."
        return f"{clean_h}. {first_sentence}"
    return f"{clean_h}."


def batch_generate_scripts_with_llm(
    headlines: List[Dict[str, Any]],
    model: str = DEFAULT_OLLAMA_MODEL,
) -> List[Dict[str, Any]]:
    """Batch-generate dynamic broadcast narration scripts in parallel utilizing all CPU cores."""
    print(f"\n🧠 Generating dynamic news anchor narration scripts via LLM ({model}, {NUM_CORES} cores)...")
    t0 = time.time()
    total = len(headlines)

    def _process_one(idx_item):
        i, item = idx_item
        headline = item.get("headline") or item.get("original_title") or ""
        summary = item.get("ai_summary") or item.get("summary") or ""
        cat = item.get("category", "General")

        script = rewrite_story_for_broadcast(
            headline=headline,
            summary=summary,
            category=cat,
            index=i,
            total=total,
            model=model,
        )
        item["narration_script"] = script
        return i, headline, script

    workers = min(4, NUM_CORES)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_process_one, enumerate(headlines, start=1)))

    for i, headline, script in sorted(results, key=lambda x: x[0]):
        print(f"  [{i:02d}/{total:02d}] {headline[:45]}...")
        print(f"        🎙️ Anchor: \"{script}\"")

    print(f"✅ Generated {total} LLM broadcast narration scripts in {time.time() - t0:.1f}s.")
    return headlines
