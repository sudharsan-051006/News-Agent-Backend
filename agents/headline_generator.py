import re
import ollama

def clean_text(text: str) -> str:
    if not text:
        return ""

    # Remove HTML tags
    text = re.sub(r"<.*?>", "", text)

    # Remove URLs (optional)
    text = re.sub(r"http\S+", "", text)

    # Remove extra spaces
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

def generate_ai_summary(article: dict) -> str:
    title = clean_text(article.get("title", ""))
    summary = clean_text(article.get("summary", ""))

    prompt = f"""
Write a concise 3-line news summary.

Rules:
- Exactly 3 lines
- Each line 12–20 words
- Neutral tone
- Do not add new facts
- Keep uncertainty words like "may", "reportedly"

Title: {title}
Summary: {summary}

Summary:
"""

    try:
        response = ollama.chat(
            model="phi",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.6}
        )

        result = response["message"]["content"].strip()

        lines = result.split("\n")
        if len(lines) >= 3:
            return "\n".join(lines[:3])

        return result

    except Exception:
        return summary[:200]


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
        summary = generate_ai_summary(article)
        
        headlines.append({
            "category": article["category"],
            "headline": headline,
            "summary": n["ai_summary"],
            "link": article["link"]
        })

    return headlines
