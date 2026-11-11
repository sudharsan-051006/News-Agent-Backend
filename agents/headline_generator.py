
import os
import re
from difflib import SequenceMatcher

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_TIMEOUT_SECONDS = 30


def clean_text(text: str) -> str:
    """Remove HTML tags, URLs and excess whitespace."""
    if not text:
        return ""

    text = re.sub(r"<.*?>", " ", str(text))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _normalize_for_compare(text: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        (text or "").lower()
    ).strip()


def _rss_summary_fallback(summary: str, reason: str) -> str:
    """Return the complete original RSS summary."""
    print(f"⚠️ Groq summary fallback: {reason}")
    return summary


def _validate_summary(result: str) -> str | None:
    """Validate the three-line AI-generated summary."""

    if not result:
        return None

    lines = []

    for raw_line in result.splitlines():
        line = re.sub(
            r"^\s*(?:[-*•]+|\d+[.)])\s*",
            "",
            raw_line
        ).strip()

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
    """Generate a factual three-line summary using the configured Groq model."""

    title = clean_text(
        article.get("title")
        or article.get("original_title")
        or ""
    )

    original_summary = clean_text(
        article.get("summary") or ""
    )

    if not original_summary:
        return _rss_summary_fallback(
            "",
            "RSS article has no summary"
        )

    # Read credentials from environment variables.
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "").strip()

    if not api_key:
        return _rss_summary_fallback(
            original_summary,
            "GROQ_API_KEY is missing or empty"
        )

    if not model:
        return _rss_summary_fallback(
            original_summary,
            "GROQ_MODEL is missing or empty"
        )

    prompt = f"""
Create a genuinely rewritten, factual summary of this news article.

Requirements:
- Return exactly three separate lines.
- Do not include headings, numbering or bullet symbols.
- Each line must contain 12 to 20 words.
- Line 1: Main event and key actors.
- Line 2: Important details, figures, location or context.
- Line 3: Consequence, response or next development, if available.
- Use different wording and sentence structure from the RSS summary.
- Do not copy the RSS summary sentence by sentence.
- Never invent details, causes, quotes, figures or conclusions.
- Preserve uncertainty and attribution.
- If information is unavailable, do not speculate.
- Use neutral, concise news-writing style.

Article title:
{title}

Original RSS summary:
{original_summary}

Rewritten three-line summary:
""".strip()

    try:
        client = Groq(
            api_key=api_key,
            timeout=GROQ_TIMEOUT_SECONDS,
            max_retries=1
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful news editor. Summarize only "
                        "the supplied article information. Never add "
                        "facts or editorial opinions."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=220
        )

        result = (
            response.choices[0].message.content or ""
        ).strip()

        validated = _validate_summary(result)

        if not validated:
            return _rss_summary_fallback(
                original_summary,
                "Groq returned an empty or incorrectly formatted summary"
            )

        # Detect summaries that are almost identical to the RSS source.
        source_norm = _normalize_for_compare(original_summary)
        result_norm = _normalize_for_compare(validated)

        if source_norm and result_norm:
            similarity = SequenceMatcher(
                None,
                source_norm,
                result_norm
            ).ratio()

            if similarity >= 0.92:
                return _rss_summary_fallback(
                    original_summary,
                    "Groq output was almost identical to the RSS summary"
                )

        print(
            f"✅ Groq summary generated using model {model}: "
            f"{title[:80]}"
        )

        return validated

    except Exception as exc:
        return _rss_summary_fallback(
            original_summary,
            f"{type(exc).__name__}: {exc}"
        )


def generate_headline(article: dict) -> str:
    """Use the original RSS title as the headline."""

    title = clean_text(
        article.get("title")
        or article.get("original_title")
        or ""
    )

    if title:
        if len(title) <= 120:
            return title

        return title[:117].rsplit(" ", 1)[0] + "..."

    summary = clean_text(article.get("summary") or "")

    if summary:
        return summary[:117].rsplit(" ", 1)[0] + "..."

    return "News update"


def generate_headlines(articles):
    """Generate headline and summary pairs for articles."""

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
