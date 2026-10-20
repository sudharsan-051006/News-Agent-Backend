"""Lightweight event grouping and news-momentum scoring for Elinity.

This MVP groups similar headlines using token overlap. It is intentionally
transparent and does not claim to measure social-media popularity.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

STOPWORDS = {
    "about", "after", "again", "amid", "among", "and", "are", "around",
    "because", "been", "before", "being", "between", "but", "could",
    "from", "have", "into", "its", "just", "more", "most", "near",
    "over", "said", "says", "than", "that", "the", "their", "them",
    "there", "these", "they", "this", "those", "through", "under",
    "was", "were", "what", "when", "where", "which", "while", "with",
    "will", "would", "you", "your", "new", "latest", "live", "update",
}


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", (title or "").lower())
    return {word for word in words if word not in STOPWORDS}


def similarity(left: str, right: str) -> float:
    a, b = title_tokens(left), title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def event_key(title: str, category: str) -> str:
    tokens = sorted(title_tokens(title))
    # Keep a deterministic key, while event matching also uses similarity.
    return f"{(category or 'general').strip().lower()}:{'-'.join(tokens[:8]) or 'untitled'}"


def publisher_from_feed(feed_url: str) -> str:
    try:
        host = (urlparse(feed_url).hostname or "unknown").lower()
        return host.removeprefix("www.")
    except ValueError:
        return "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def score_event(recent_count: int, previous_count: int, publisher_count: int) -> tuple[float, str]:
    """Return a simple 0-100 news signal and a descriptive status.

    This is a first-pass heuristic, not a calibrated prediction model.
    """
    growth = max(0, recent_count - previous_count)
    growth_rate = growth / max(previous_count, 1)
    volume_signal = min(1.0, math.log1p(recent_count) / math.log(11))
    breadth_signal = min(1.0, publisher_count / 5.0)
    momentum_signal = min(1.0, growth_rate / 2.0)
    score = round(100 * (0.45 * volume_signal + 0.30 * breadth_signal + 0.25 * momentum_signal), 1)

    if recent_count == 0:
        status = "quiet"
    elif recent_count > previous_count and growth > 0:
        status = "rising"
    elif recent_count >= previous_count and recent_count >= 2:
        status = "sustained"
    else:
        status = "cooling"
    return score, status


def published_at_or_now(value: str | None) -> str:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass
    return utc_now().isoformat()


def event_window_bounds(hours: int = 2) -> tuple[str, str, str]:
    now = utc_now()
    current_start = now - timedelta(hours=hours)
    previous_start = now - timedelta(hours=hours * 2)
    return current_start.isoformat(), previous_start.isoformat(), now.isoformat()
