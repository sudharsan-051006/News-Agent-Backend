import re
import ollama

def clean_text(text: str) -> str:
    """Remove HTML tags and extra spaces"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def generate_ai_headline(article: dict) -> str:
    prompt = f"""
Rewrite as a short, factual news headline.
Preserve uncertainty words like "reportedly", "may", "according to reports".
Do NOT assume the event has already happened.
Limit to 12 words.

Title: {article.get("title", "")}
Summary: {article.get("summary", "")}

Headline:
"""

    try:
        response = ollama.chat(
            model="phi",   # or "phi"
            messages=[{"role": "user", "content": prompt}]
        )

        return response["message"]["content"].strip()

    except Exception:
        # Fallback if Ollama fails
        return article.get("title", "")

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


