
import os
import re
from pathlib import Path
from difflib import SequenceMatcher

from dotenv import load_dotenv, find_dotenv, dotenv_values
from groq import Groq


# ============================================================
# ENVIRONMENT CONFIGURATION
# ============================================================

DOTENV_PATH = find_dotenv(usecwd=True)

if DOTENV_PATH:
    load_dotenv(DOTENV_PATH, override=False)
    print(f"✅ Loaded .env file: {DOTENV_PATH}")
else:
    print("⚠️ No .env file found in the current directory hierarchy.")

GROQ_TIMEOUT_SECONDS = 30

_GROQ_DIAGNOSTIC_DONE = False


# ============================================================
# GROQ CONFIGURATION DIAGNOSTICS
# ============================================================

def diagnose_groq_config():
    """Diagnose why GROQ_MODEL may be missing or empty."""

    global _GROQ_DIAGNOSTIC_DONE

    if _GROQ_DIAGNOSTIC_DONE:
        return

    _GROQ_DIAGNOSTIC_DONE = True

    print("\n" + "=" * 60)
    print("             GROQ CONFIGURATION DIAGNOSTICS")
    print("=" * 60)

    print("Current working directory:", Path.cwd())
    print("Running in GitHub Actions:", os.getenv("GITHUB_ACTIONS", "False"))

    # Environment variable check.
    env_exists = "GROQ_MODEL" in os.environ
    env_model = os.environ.get("GROQ_MODEL", "")

    print("\n[ENVIRONMENT VARIABLES]")

    print("GROQ_MODEL key exists:", env_exists)
    print("GROQ_MODEL is empty:", not bool(env_model.strip()))
    print("GROQ_MODEL value:", repr(env_model))

    print(
        "GROQ_API_KEY configured:",
        bool(os.getenv("GROQ_API_KEY", "").strip())
    )

    # .env file check.
    print("\n[DOTENV FILE]")

    print("Found .env file:", bool(DOTENV_PATH))
    print(".env path:", DOTENV_PATH or "Not found")

    dotenv_model = ""

    if DOTENV_PATH:
        dotenv_data = dotenv_values(DOTENV_PATH)
        dotenv_model = (
            dotenv_data.get("GROQ_MODEL") or ""
        ).strip()

    print(".env contains GROQ_MODEL:", bool(dotenv_model))
    print(".env model value:", repr(dotenv_model))

    # Diagnosis.
    print("\n[DIAGNOSIS]")

    if env_model.strip():
        print("✅ GROQ_MODEL is available from the process environment.")

    elif env_exists and dotenv_model:
        print("❌ Environment GROQ_MODEL exists but is EMPTY.")
        print("   A valid .env value cannot override it because")
        print("   load_dotenv() uses override=False.")
        print("   Fix the deployment environment variable.")

    elif env_exists:
        print("❌ GROQ_MODEL exists but has an empty value.")
        print("   Check GitHub Actions Variables and workflow configuration.")

    elif dotenv_model:
        print("⚠️ .env has GROQ_MODEL but it was not loaded.")
        print("   Check the .env path and loading configuration.")

    else:
        print("❌ GROQ_MODEL is missing from both environment and .env.")
        print("   Configure GROQ_MODEL in your deployment environment.")

    print("=" * 60 + "\n")


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text: str) -> str:
    """Remove HTML tags, URLs and excess whitespace."""

    if not text:
        return ""

    text = re.sub(r"<.*?>", " ", str(text))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _normalize_for_compare(text: str) -> str:
    """Normalize text before similarity comparison."""

    return re.sub(
        r"[^a-z0-9]+",
        "",
        (text or "").lower()
    ).strip()


# ============================================================
# RSS FALLBACK
# ============================================================

def _rss_summary_fallback(summary: str, reason: str) -> str:
    """Return the complete original RSS summary."""

    print(f"⚠️ Groq summary fallback: {reason}")

    return summary


# ============================================================
# SUMMARY VALIDATION
# ============================================================

def _validate_summary(result: str) -> str | None:
    """Accept exactly three lines with 12-20 words each."""

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

        word_count = len(
            re.findall(r"\b[\w’'-]+\b", line)
        )

        if not 12 <= word_count <= 20:
            return None

    return "\n".join(lines)


# ============================================================
# AI SUMMARY GENERATION
# ============================================================

def generate_ai_summary(article: dict) -> str:
    """
    Generate a factual three-line news summary using Groq.

    The model is read directly from GROQ_MODEL.
    No hardcoded model or automatic model substitution.

    If Groq fails, return the original RSS summary.
    """

    # Run configuration diagnostics once.
    diagnose_groq_config()

    title = clean_text(
        article.get("title")
        or article.get("original_title")
        or ""
    )

    original_summary = clean_text(
        article.get("summary") or ""
    )

    # Check original RSS summary.
    if not original_summary:

        return _rss_summary_fallback(
            "",
            "RSS article has no summary"
        )

    # Read API key.
    api_key = os.getenv(
        "GROQ_API_KEY",
        ""
    ).strip()

    if not api_key:

        return _rss_summary_fallback(
            original_summary,
            "GROQ_API_KEY is missing or empty"
        )

    # Read exact model from environment.
    model = os.getenv(
        "GROQ_MODEL",
        ""
    ).strip()

    if not model:

        return _rss_summary_fallback(
            original_summary,
            "GROQ_MODEL is missing or empty"
        )

    # Prompt for Groq.
    prompt = f"""
Create a genuinely rewritten, factual summary of this news article.

Requirements:
- Return exactly three separate lines.
- No heading, numbering or bullet symbols.
- Each line must contain 12 to 20 words.
- Line 1: Main event and key actors.
- Line 2: Important details, figures, location or context.
- Line 3: Consequence, response or next development, if available.
- Use different wording and sentence structure from the RSS summary.
- Do not copy the RSS summary sentence by sentence.
- Never invent details, causes, quotes, figures or conclusions.
- Preserve uncertainty and attribution words.
- Do not speculate when information is unavailable.
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

        # Validate response.
        validated = _validate_summary(result)

        if not validated:

            return _rss_summary_fallback(
                original_summary,
                "Groq returned an empty or incorrectly formatted summary"
            )

        # Detect nearly identical RSS summaries.
        source_norm = _normalize_for_compare(
            original_summary
        )

        result_norm = _normalize_for_compare(
            validated
        )

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


# ============================================================
# HEADLINE GENERATION
# ============================================================

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

    summary = clean_text(
        article.get("summary") or ""
    )

    if summary:

        return summary[:117].rsplit(" ", 1)[0] + "..."

    return "News update"


# ============================================================
# PROCESS MULTIPLE ARTICLES
# ============================================================

def generate_headlines(articles):
    """Generate headline and summary pairs for articles."""

    headlines = []

    for article in articles:

        headline = generate_headline(article)

        summary = generate_ai_summary(article)

        headlines.append({

            "category": article.get(
                "category",
                "General"
            ),

            "headline": headline,

            "summary": summary,

            "link": article.get(
                "link",
                ""
            )

        })

    return headlines
