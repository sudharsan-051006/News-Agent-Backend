"""
Utility functions for Elinity Fiction Engine.
Provides prompt loading, robust JSON parsing from LLM outputs, and string cleanup.
"""

import os
import re
import json
import logging
from typing import Any, Optional, Dict, List
from datetime import datetime, date

logger = logging.getLogger("fiction.utils")


def load_prompt(prompt_name: str) -> str:
    """Loads a prompt template from fiction/prompts directory."""
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    file_path = os.path.join(prompt_dir, prompt_name)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Prompt template {prompt_name} not found in {prompt_dir}")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def parse_llm_json(raw_text: str) -> Any:
    """
    Robustly extracts and parses JSON (object or array) from LLM output.
    Handles markdown fences, trailing commas, and prefix/suffix commentary.
    """
    if not raw_text:
        return None

    # 1. Strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()

    # 2. Locate outermost JSON structure
    first_bracket = cleaned.find("[")
    first_brace = cleaned.find("{")

    # Determine whether array or object starts first
    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        last_bracket = cleaned.rfind("]")
        if last_bracket > first_bracket:
            json_str = cleaned[first_bracket : last_bracket + 1]
        else:
            json_str = cleaned[first_bracket:]
    elif first_brace != -1:
        last_brace = cleaned.rfind("}")
        if last_brace > first_brace:
            json_str = cleaned[first_brace : last_brace + 1]
        else:
            json_str = cleaned[first_brace:]
    else:
        return None

    # 3. Clean trailing commas before closing braces/brackets
    json_str = re.sub(r",\s*([\]}])", r"\1", json_str)

    try:
        return json.loads(json_str)
    except Exception as e:
        logger.warning(f"Standard JSON parse failed ({e}). Attempting heuristic recovery...")
        # Fallback regex extraction of JSON objects
        matches = re.findall(r"\{[^{}]*\}", json_str)
        recovered = []
        for m in matches:
            clean_m = re.sub(r",\s*([\]}])", r"\1", m)
            try:
                recovered.append(json.loads(clean_m))
            except Exception:
                continue
        if recovered:
            return recovered
        return None


def parse_iso_date(date_str: Optional[str]) -> Optional[date]:
    """Safely parses a string date into a datetime.date object."""
    if not date_str or date_str.lower() in ["null", "none", "unknown"]:
        return None
    date_str = str(date_str).strip()
    for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%d-%m-%Y", "%B %d, %Y"]:
        try:
            return datetime.strptime(date_str[:10], fmt[: len(date_str[:10])]).date()
        except Exception:
            continue
    return None
