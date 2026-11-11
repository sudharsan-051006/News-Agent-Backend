import os
import re
from difflib import SequenceMatcher

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TIMEOUT_SECONDS = 30


def clean_text(text: str) -> str:
    """Remove HTML tags, URLs and excess whitespace from feed text."""
    if not text:
        return ""

    text = re.sub(r"<.*?>", " ", str(text))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower()).strip()


def _rss_summary_fallback(summary: str, reason: str) -> str:
    """Return the original feed summary when Groq is unavailable or invalid."""
    print(f"⚠️ Groq summary fallback: {reason}")
    return summary[:200]


def _validate_summary(result: str) -> str | None:
    """Accept only three meaningful, correctly sized summary lines."""
    if not result:
        return None

    lines = []
    for raw_line in result.splitlines():
        line = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", raw_line).strip()
        if line:
            lines.append(line)

    if len(lines) != 3:
        return None

    for line in lines:
        word_count = len(re.findall(r"\b[\w’'-]+\b", line))
        if not 12 <= word_count <= 20:
            return None

    return "\n".join(lines)


def generate_ai_summary(article: dict) -> str:
    """Generate a factual three-line news summary with Groq.

    If the API key is missing, the request fails, or the response does not
    pass validation, return the original RSS summary as a safe fallback.
    """
    title = clean_text(article.get("title") or article.get("original_title") or "")
    original_summary = clean_text(article.get("summary") or "")

    if not original_summary:
        return _rss_summary_fallback("", "RSS article has no summary to summarize")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return _rss_summary_fallback(
            original_summary,
            "GROQ_API_KEY is not configured",
        )

    prompt = f"""
Create a genuinely rewritten, factual summary of this news article.

Requirements:
- Return exactly three separate lines, with no heading, numbering or bullet symbols.
- Each line must contain 12 to 20 words.
- Line 1: the main event and the key actors.
- Line 2: the most important details, figures, location or context stated in the source.
- Line 3: the reported consequence, response or next development, if the source provides one.
- Use different wording and sentence structure from the supplied RSS summary.
- Do not copy the RSS summary sentence by sentence.
- Do not invent details, causes, quotes, figures or conclusions.
- Preserve uncertainty and attribution words such as "may", "reportedly" and "according to".
- If the source lacks information for a line, state only what is supported; do not speculate.
- Use a neutral, concise news-writing style.

Article title:
{title}

Original RSS summary:
{original_summary}

Rewritten three-line summary:
""".strip()

    try:
        client = Groq(api_key=api_key, timeout=GROQ_TIMEOUT_SECONDS, max_retries=1)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful news editor. Summarize only the supplied "
                        "article information. Never add facts or editorial opinions."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=220,
        )

        result = (response.choices[0].message.content or "").strip()
        validated = _validate_summary(result)
        if not validated:
            return _rss_summary_fallback(
                original_summary,
                "Groq returned an empty or incorrectly formatted summary",
            )

        # Guard against a model response that simply copies the feed description.
        source_norm = _normalize_for_compare(original_summary)
        result_norm = _normalize_for_compare(validated)
        if source_norm and result_norm:
            similarity = SequenceMatcher(None, source_norm, result_norm).ratio()
            if similarity >= 0.92:
                return _rss_summary_fallback(
                    original_summary,
                    "Groq output was almost identical to the RSS summary",
                )

        print(f"✅ Groq summary generated using model {GROQ_MODEL}: {title[:80]}")
        return validated

    except Exception as exc:
        return _rss_summary_fallback(
            original_summary,
            f"{type(exc).__name__}: {exc}",
        )


def generate_headline(article: dict) -> str:
    """Use the existing AI headline hook when available, otherwise use RSS text."""
    try:
        ai_headline = generate_ai_headline(article)  # noqa: F821
        if ai_headline and len(ai_headline) <= 120:
            return ai_headline.strip()
    except Exception as exc:
        print(f"⚠️ AI headline generation unavailable: {type(exc).__name__}: {exc}")

    title = clean_text(article.get("title") or article.get("original_title") or "")
    summary = clean_text(article.get("summary") or "")
    if len(title) <= 90:
        return title
    return (summary[:87] + "...") if summary else title[:90]


def generate_headlines(articles):
    """Generate headline and summary pairs for a list of articles."""
    headlines = []
    for article in articles:
        headline = generate_headline(article)
        summary = generate_ai_summary(article)
        headlines.append({
            "category": article.get("category", "General"),
            "headline": headline,
            "summary": summary,
            "link": article.get("link", ""),
        })
    return headlines
