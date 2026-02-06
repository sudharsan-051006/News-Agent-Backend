import re
import ollama

def clean_text(text: str) -> str:
    """Remove HTML tags and extra spaces"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_for_compare(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "", text.lower())
    return text.strip()

def _is_too_similar(candidate: str, title: str) -> bool:
    if not candidate or not title:
        return False
    candidate_norm = _normalize_for_compare(candidate)
    title_norm = _normalize_for_compare(title)
    if not candidate_norm or not title_norm:
        return False
    if candidate_norm == title_norm:
        return True
    return candidate_norm in title_norm or title_norm in candidate_norm

def generate_ai_headline(article: dict) -> str:
    title = article.get("title", "")
    summary = article.get("summary", "")
    base_prompt = f"""
Rewrite the following into a 1–2 sentence neutral news summary.
Do not add new facts.
Keep uncertainty words.
Min 15 words.
Max 30 words.
Preserve uncertainty words like "reportedly", "may", "according to reports".
Do NOT assume the event has already happened.

Title: {title}
Summary: {summary}

Headline:
"""

    try:
        response = ollama.chat(
            model="phi",   # or "phi"
            messages=[{"role": "user", "content": base_prompt}],
            options={"temperature": 0.7}
        )

        headline = response["message"]["content"].strip()
        if _is_too_similar(headline, title):
            retry_prompt = f"""
Rewrite the headline using different wording from the original title.
Avoid copying phrases from the title.
Keep it factual and under 12 words.

Title: {title}
Summary: {summary}

Headline:
"""
            response = ollama.chat(
                model="phi",   # or "phi"
                messages=[{"role": "user", "content": retry_prompt}],
                options={"temperature": 0.8}
            )
            headline = response["message"]["content"].strip()

        if _is_too_similar(headline, title):
            return ""

        return headline

    except Exception:
        # Fallback if Ollama fails
        return title

def generate_headline(article: dict) -> str:
    """
    Uses AI headline generation with safe fallback.
    """

    try:
        ai_headline = generate_ai_headline(article)

        # Safety checks
        if ai_headline and len(ai_headline) <= 120:
            return ai_headline

    except Exception:
        pass

    # ---- FALLBACK (rule-based) ----
    title = clean_text(article.get("title", ""))
    summary = clean_text(article.get("summary", ""))

    if len(title) <= 90:
        return title

    return summary[:90] + "..."

def generate_headlines(articles):
    headlines = []

    for article in articles:
        headline = generate_headline(article)
        headlines.append({
            "category": article["category"],
            "headline": headline,
            "link": article["link"]
        })

    return headlines
