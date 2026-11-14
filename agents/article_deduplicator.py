"""Content-based article deduplication for Elinity; categories are never inspected."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "ref", "ref_src", "source", "campaign", "igshid",
}
TRACKING_PREFIXES = ("utm_",)
WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
TITLE_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "for", "to", "of", "in", "on",
    "at", "by", "as", "is", "are", "was", "were", "be", "been", "with",
    "from", "after", "before", "over", "into", "about", "how", "why",
    "what", "who", "when", "where", "live", "updates", "update", "latest",
    "breaking", "watch", "read", "explained", "highlights",
}


def _first_nonempty(article: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = article.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_text(value: Any) -> str:
    """Normalize HTML/text for hashing and similarity checks."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"https?://\S+", " ", text)
    return SPACE_RE.sub(" ", text).strip()


def normalize_url(value: Any) -> str:
    """Remove fragments/tracking parameters and normalize common URL variants."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if not parts.scheme or not parts.netloc:
            return raw.rstrip("/")
        scheme = parts.scheme.casefold()
        hostname = (parts.hostname or "").casefold()
        if not hostname:
            return raw.rstrip("/")
        try:
            port = parts.port
        except ValueError:
            port = None
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc = f"{hostname}:{port}"
        else:
            netloc = hostname
        path = parts.path or "/"
        if path != "/":
            path = path.rstrip("/")
        kept = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            lowered = key.casefold()
            if lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES):
                continue
            kept.append((key, val))
        return urlunsplit((scheme, netloc, path, urlencode(sorted(kept), doseq=True), ""))
    except Exception:
        return raw.rstrip("/")


def _headline(article: dict[str, Any]) -> str:
    return _first_nonempty(article, ("title", "headline", "name"))


def _url(article: dict[str, Any]) -> str:
    return _first_nonempty(article, ("url", "link", "article_url", "canonical_url"))


def _body(article: dict[str, Any]) -> str:
    return _first_nonempty(article, ("content", "text", "article_text", "full_text", "summary", "description"))


def _source(article: dict[str, Any]) -> str:
    return _first_nonempty(article, ("source_name", "source", "publisher", "feed_title"))


def _published(article: dict[str, Any]) -> str:
    return _first_nonempty(article, ("published_at", "published", "pubDate", "date"))


def _content_hash(article: dict[str, Any]) -> str:
    body = normalize_text(_body(article))
    if len(body) < 80:
        return ""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _title_tokens(article: dict[str, Any]) -> set[str]:
    tokens = set(WORD_RE.findall(normalize_text(_headline(article))))
    return {word for word in tokens if word not in TITLE_STOPWORDS and len(word) > 1}


def _title_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    title_a, title_b = normalize_text(_headline(a)), normalize_text(_headline(b))
    if not title_a or not title_b:
        return 0.0
    seq = SequenceMatcher(None, title_a, title_b).ratio()
    ta, tb = _title_tokens(a), _title_tokens(b)
    overlap = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return max(seq, 0.65 * overlap + 0.35 * seq)


def _body_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    body_a, body_b = normalize_text(_body(a)), normalize_text(_body(b))
    if min(len(body_a), len(body_b)) < 120:
        return 0.0
    body_a, body_b = body_a[:6000], body_b[:6000]
    seq = SequenceMatcher(None, body_a, body_b, autojunk=True).ratio()
    words_a, words_b = set(WORD_RE.findall(body_a)), set(WORD_RE.findall(body_b))
    overlap = len(words_a & words_b) / len(words_a | words_b) if words_a and words_b else 0.0
    return max(seq, overlap)


def _parse_time(value: str) -> float | None:
    if not value:
        return None
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _same_story(a: dict[str, Any], b: dict[str, Any], title_threshold: float,
                body_threshold: float, time_window_hours: int) -> bool:
    time_a, time_b = _parse_time(_published(a)), _parse_time(_published(b))
    if time_a is not None and time_b is not None:
        if abs(time_a - time_b) > time_window_hours * 3600:
            return False
    title_score = _title_similarity(a, b)
    body_score = _body_similarity(a, b)
    # Similar full text catches syndicated copies with rewritten headlines.
    if body_score >= body_threshold:
        return True
    # With no strong body match, require a very strong title match plus some
    # body overlap. This helps avoid merging unrelated stories sharing keywords.
    return title_score >= title_threshold and body_score >= 0.35


def _quality_score(article: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        len(normalize_text(_body(article))),
        len(normalize_text(_headline(article))),
        int(bool(normalize_url(_url(article)))),
        _published(article),
    )


def _merge_representative(representative: dict[str, Any], group: list[dict[str, Any]]) -> dict[str, Any]:
    result = dict(representative)
    sources, urls, categories = [], [], []
    for article in group:
        source, url = _source(article), _url(article)
        category = str(article.get("category") or "").strip()
        if source and source not in sources:
            sources.append(source)
        if url and url not in urls:
            urls.append(url)
        if category and category not in categories:
            categories.append(category)
    # Category is metadata only: it is never used to decide whether articles match.
    result["categories"] = categories
    result["sources"] = sources
    result["duplicate_count"] = len(group) - 1
    result["duplicate_sources"] = sources
    result["duplicate_urls"] = urls
    return result


def deduplicate_articles(
    articles: list[dict[str, Any]], *, title_threshold: float = 0.88,
    body_threshold: float = 0.82, time_window_hours: int = 72,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (unique_articles, duplicate_groups). Categories are never used for matching; associations are preserved in the output.

    Input dictionaries may use title/headline, url/link, content/text/summary,
    source/source_name, and published_at/published fields. The function copies
    input records and does not mutate or delete anything in the database.
    """
    records = [dict(item) for item in articles if isinstance(item, dict)]
    records.sort(key=_quality_score, reverse=True)
    groups: list[list[dict[str, Any]]] = []
    url_index: dict[str, int] = {}
    hash_index: dict[str, int] = {}

    for article in records:
        url_key, hash_key = normalize_url(_url(article)), _content_hash(article)
        group_index = url_index.get(url_key) if url_key else None
        if group_index is None and hash_key:
            group_index = hash_index.get(hash_key)
        if group_index is None:
            for idx, group in enumerate(groups):
                if _same_story(article, group[0], title_threshold, body_threshold, time_window_hours):
                    group_index = idx
                    break
        if group_index is None:
            group_index = len(groups)
            groups.append([])
        groups[group_index].append(article)
        if url_key:
            url_index[url_key] = group_index
        if hash_key:
            hash_index[hash_key] = group_index

    unique, duplicate_groups = [], []
    for group in groups:
        representative = _merge_representative(group[0], group)
        unique.append(representative)
        if len(group) > 1:
            duplicate_groups.append({
                "representative": representative,
                "duplicates": [dict(item) for item in group[1:]],
                "match_count": len(group),
            })
    return unique, duplicate_groups


def deduplicate_articles_only(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convenience wrapper when only the unique list is needed."""
    return deduplicate_articles(articles)[0]
