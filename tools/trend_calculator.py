"""
Dynamic Event Discovery & Quantitative 6-Day Trend Velocity Engine.
1. Discovers on-the-fly event categories (e.g. 'Cyclone Dana', 'Ukraine Peace Talks', 'Razorpay IPO').
2. Classifies each topic as INDIA or GLOBAL.
3. Records EVERY single discovered topic into Neon DB (including rare 1-mention seed topics for future tracking).
4. Extracts Top 5 Global and Top 5 India trending topics for the daily email briefing.
"""

import re
import json
import logging
from typing import Dict, List, Any, Tuple, Optional
from database import get_six_day_topic_baseline, record_topic_snapshot
from llm_adapter import llm_client
from config import settings
from tools.image_finder import find_internet_image

logger = logging.getLogger("agent.tools.trend")

PILLAR_FALLBACK_IMAGES = {
    "Technology & AI": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1200&q=80",
    "Geopolitics & Security": "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1200&q=80",
    "Geopolitics": "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1200&q=80",
    "India Affairs": "https://images.unsplash.com/photo-1532375810709-75b1da00537c?auto=format&fit=crop&w=1200&q=80",
    "Finance & Markets": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&q=80",
    "General News": "https://images.unsplash.com/photo-1504711434969-e33886168f5c?auto=format&fit=crop&w=1200&q=80"
}


def clean_and_parse_json(raw_text: str) -> Optional[List[Dict[str, Any]]]:
    """Robustly extracts and parses JSON array from LLM output, handling trailing commas and markdown fences."""
    if not raw_text:
        return None
    # 1. Remove markdown code fences
    cleaned = re.sub(r'```(?:json)?', '', raw_text)
    
    # 2. Extract outermost [ ... ]
    start = cleaned.find('[')
    end = cleaned.rfind(']')
    if start != -1 and end != -1 and end > start:
        json_str = cleaned[start:end+1]
    else:
        return None

    # 3. Remove trailing commas before closing braces/brackets (e.g. [1, 2,] or {"a": 1,})
    json_str = re.sub(r',\s*([\]}])', r'\1', json_str)

    try:
        return json.loads(json_str)
    except Exception as e:
        logger.warning(f"Standard JSON parse failed ({e}), attempting object-by-object recovery...")
        # 4. Fallback: Extract individual JSON objects {...}
        try:
            object_matches = re.findall(r'\{[^{}]*\}', json_str)
            parsed_objs = []
            for obj_str in object_matches:
                clean_obj = re.sub(r',\s*([\]}])', r'\1', obj_str)
                try:
                    parsed_objs.append(json.loads(clean_obj))
                except Exception:
                    continue
            if parsed_objs:
                return parsed_objs
        except Exception:
            pass
        return None


def discover_dynamic_topics(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Uses LLM to perform zero-shot dynamic event discovery across all ingested headlines.
    Discovers specific event categories on-the-fly rather than forcing static buckets.
    """
    valid_articles = [a for a in articles[:50] if a.get("title")]
    sample_headlines = [
        {"id": idx + 1, "title": a.get("title", ""), "source": a.get("feed_name", "News Source")} 
        for idx, a in enumerate(valid_articles)
    ]

    prompt = f"""
You are an expert news intelligence analyst.
Analyze the following list of news headlines from today collected across multiple sources.
Your job is to cluster them into distinct, descriptive dynamic topic categories and autonomously identify their true topic domain.

CRITICAL RULES:
1. AGGRESSIVE MERGING: If multiple headlines report on the SAME real-world event or story (e.g. multiple outlets reporting on Sooryavanshi captaincy, Yes Bank fraud denial, Gurnoor Brar in Test squad, or Stiglitz at HTLS), you MUST combine all their IDs into ONE single topic object! Do NOT output separate duplicate topics for the same story.
2. EXACT ARTICLE IDS: The "article_ids" array MUST contain the EXACT integer "id" values (1 to {len(sample_headlines)}) corresponding to the headlines covering this event from the list below. EVERY topic must include its matching article IDs.
3. "topic_name": Descriptive 3-6 word event title (e.g. 'Cyclone Dana Coastal Landfall', 'UN Security Council Truce', 'IPL Mega Auction Trades', 'OpenAI Claude Lawsuit', 'Box Office Opening Record').
4. "pillar": Dynamically identify and assign the natural category based strictly on the content of the story. Examples:
   - "Technology & AI"
   - "Geopolitics & Security"
   - "India Affairs"
   - "Finance & Markets"
   - "Sports"
   - "Entertainment & Movies"
   - "Science & Environment"
5. "scope": Classify as "INDIA" or "GLOBAL".
6. "why_trending": 1-2 clear sentences explaining the EXACT CATALYST or EVENT—specifically WHY this story broke out in the news today.
7. "summary": 1-2 sentence objective summary of the event.
8. "keywords": 3-5 core keywords.
9. "article_ids": list of integer IDs from the input that belong to this topic.

HEADLINES:
{json.dumps(sample_headlines, indent=1)}

OUTPUT FORMAT:
Return ONLY a valid JSON array of objects with keys:
- "topic_name": string
- "pillar": string
- "scope": "INDIA" or "GLOBAL"
- "why_trending": string
- "summary": string
- "keywords": list of strings
- "article_ids": list of integers
"""

    try:
        raw_response = llm_client.generate(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2500
        )
        
        clusters = clean_and_parse_json(raw_response)
        if clusters:
            logger.info(f"Successfully discovered {len(clusters)} dynamic event categories.")
            
            # Map back article data to each cluster (supporting 1-based and 0-based LLM quirks)
            id_to_article = {idx + 1: a for idx, a in enumerate(valid_articles)}
            
            for c in clusters:
                assigned = []
                for aid in c.get("article_ids", []):
                    art = id_to_article.get(aid) or (valid_articles[aid] if 0 <= aid < len(valid_articles) else None)
                    if art and art not in assigned:
                        assigned.append(art)
                
                # Content alignment & verification check:
                # Prevent index-shift bugs where a topic gets assigned an unrelated article (e.g. Ukraine assigned Amtrak)
                t_words = set(re.findall(r"\w+", c.get("topic_name", "").lower()))
                t_words = {w for w in t_words if len(w) > 3 and w not in ["news", "today", "report", "says", "amid", "with", "after"]}
                
                is_valid = False
                if assigned:
                    for a in assigned:
                        a_words = set(re.findall(r"\w+", a.get("title", "").lower()))
                        if not t_words or (t_words & a_words):
                            is_valid = True
                            break
                
                if not is_valid:
                    # Index was shifted or empty! Find the true matching article from input by word overlap
                    logger.warning(f"Re-aligning articles for topic '{c.get('topic_name')}' by title similarity.")
                    best_art = None
                    best_score = 0
                    for a in valid_articles:
                        a_words = set(re.findall(r"\w+", a.get("title", "").lower()))
                        score = len(t_words & a_words)
                        if score > best_score:
                            best_score = score
                            best_art = a
                    if best_art and best_score > 0:
                        assigned = [best_art]

                c["articles"] = assigned
                c["article_count"] = max(len(assigned), 1)

            # Intra-run deduplication: Merge duplicate clusters for the same event
            merged_clusters = []
            for c in clusters:
                c_words = set(re.findall(r"\w+", c.get("topic_name", "").lower()))
                c_words = {w for w in c_words if len(w) > 3 and w not in ["news", "today", "report", "says", "amid", "with", "after"]}
                
                merged = False
                for existing in merged_clusters:
                    e_words = set(re.findall(r"\w+", existing.get("topic_name", "").lower()))
                    e_words = {w for w in e_words if len(w) > 3 and w not in ["news", "today", "report", "says", "amid", "with", "after"]}
                    
                    overlap = len(c_words & e_words) / len(c_words | e_words) if (c_words | e_words) else 0
                    if overlap >= 0.35:
                        logger.info(f"Merging duplicate clusters: '{c.get('topic_name')}' into '{existing.get('topic_name')}'")
                        existing_urls = {a.get("url") for a in existing.get("articles", [])}
                        for a in c.get("articles", []):
                            if a.get("url") and a.get("url") not in existing_urls:
                                existing["articles"].append(a)
                                existing_urls.add(a.get("url"))
                        existing["article_count"] = len(existing["articles"])
                        merged = True
                        break
                
                if not merged:
                    merged_clusters.append(c)

            # Ensure strictly non-empty clusters with at least one verified reference article
            return [c for c in merged_clusters if c.get("articles") and len(c["articles"]) > 0]
        else:
            logger.warning("Failed to parse JSON clusters from LLM. Falling back to rule-based fallback.")
    except Exception as e:
        logger.error(f"Error in dynamic topic discovery: {e}. Using fallback clustering.")

    # Fallback if LLM JSON parsing fails
    return fallback_clustering(articles)


def fallback_clustering(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Emergency heuristic fallback if LLM clustering is unavailable."""
    clusters = []
    for idx, a in enumerate(articles[:30]):
        title = a.get("title", "")
        t_lower = title.lower()
        
        # Content-based autonomous pillar detection
        if any(w in t_lower for w in ["cricket", "ipl", "match", "football", "goal", "wicket", "test match", "sports"]):
            cat = "Sports"
        elif any(w in t_lower for w in ["movie", "film", "box office", "actor", "actress", "cinema", "trailer", "ott"]):
            cat = "Entertainment & Movies"
        elif any(w in t_lower for w in ["sensex", "nifty", "shares", "stock", "ipo", "yield", "bonds", "pat", "inflation", "fed"]):
            cat = "Finance & Markets"
        elif any(w in t_lower for w in ["ai", "microsoft", "tech", "nvidia", "claude", "software", "chip", "google", "apple", "app"]):
            cat = "Technology & AI"
        elif any(w in t_lower for w in ["india", "delhi", "mumbai", "modi", "bjp", "congress", "kerala", "parliament", "election", "bengaluru"]):
            cat = "India Affairs"
        else:
            cat = "Geopolitics & Security"

        is_india = cat == "India Affairs" or any(w in t_lower for w in ["india", "delhi", "mumbai", "modi", "rupee", "sebi", "nifty", "sensex"])
        clusters.append({
            "topic_name": title[:60],
            "pillar": cat,
            "scope": "INDIA" if is_india else "GLOBAL",
            "why_trending": f"Breaking coverage reported across {a.get('feed_name', 'major news feeds')}.",
            "keywords": [w for w in t_lower.split() if len(w) > 4][:4],
            "article_count": 1,
            "articles": [a],
            "summary": title
        })
    return clusters


def process_and_rank_trends(dynamic_topics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    1. Computes velocity scores for each dynamic topic against the 6-day baseline in Neon DB.
    2. Stores EVERY topic into Neon DB with images, why_trending, pillar, and reference links.
    3. Returns Top 5 Global and Top 5 India trending topics.
    """
    baseline_6d = get_six_day_topic_baseline()
    
    india_topics = []
    global_topics = []

    for t in dynamic_topics:
        topic_name = t.get("topic_name", "Unknown Event")
        scope = t.get("scope", "GLOBAL").upper()
        pillar = t.get("pillar", "General News")
        why_trending = t.get("why_trending", "")
        count = t.get("article_count", 1)
        keywords = t.get("keywords", [])
        summary = t.get("summary", "")
        articles_list = t.get("articles", [])

        # Extract best high-res image from cluster articles
        image_url = ""
        for a in articles_list:
            if a.get("image_url"):
                image_url = a["image_url"]
                break

        # If articles lack an image, autonomously search the internet for a relevant image!
        if not image_url:
            image_url = find_internet_image(topic_name, keywords)

        # Fallback to high-res pillar editorial image if internet search returns nothing
        if not image_url:
            image_url = PILLAR_FALLBACK_IMAGES.get(pillar, PILLAR_FALLBACK_IMAGES.get("General News", ""))

        # Package clean reference articles for the frontend
        reference_articles = [
            {
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "source": a.get("feed_name", a.get("source", "News Source")),
                "published_at": a.get("published_at").isoformat() if hasattr(a.get("published_at"), "isoformat") else str(a.get("published_at") or ""),
                "image_url": a.get("image_url", "")
            }
            for a in articles_list if a.get("url")
        ]

        # Look up 6-day baseline mentions
        avg_6d = baseline_6d.get(topic_name, 0.0)
        
        # Velocity score with smoothing epsilon = 0.5
        velocity_score = round(count / (avg_6d + 0.5), 2)

        # Categorize trend type
        if count == 1 and avg_6d == 0.0:
            trend_type = "SEED_MENTION" # Rare today, preserved for tomorrow!
        elif avg_6d == 0.0 and count >= 2:
            trend_type = "EMERGING"
        elif velocity_score >= settings.MIN_TREND_VELOCITY_SCORE and count >= 3:
            trend_type = "BREAKOUT"
        elif avg_6d >= 1.0 and count >= 2:
            trend_type = "EVOLVING"
        else:
            trend_type = "STEADY"

        # =====================================================================
        # CORE REQUIREMENT: Store EVERY topic in Neon DB with why_trending & links
        # =====================================================================
        record_topic_snapshot(
            topic_name=topic_name,
            count=count,
            trend_type=trend_type,
            velocity_score=velocity_score,
            scope=scope,
            keywords=keywords,
            summary=summary,
            pillar=pillar,
            why_trending=why_trending,
            image_url=image_url,
            reference_articles=reference_articles
        )

        topic_data = {
            "topic_name": topic_name,
            "scope": scope,
            "pillar": pillar,
            "why_trending": why_trending,
            "article_count": count,
            "velocity_score": velocity_score,
            "trend_type": trend_type,
            "summary": summary,
            "image_url": image_url,
            "keywords": keywords,
            "articles": articles_list
        }

        if scope == "INDIA":
            india_topics.append(topic_data)
        else:
            global_topics.append(topic_data)

    # Sort each list by velocity score descending, then by volume
    india_topics.sort(key=lambda x: (x["velocity_score"], x["article_count"]), reverse=True)
    global_topics.sort(key=lambda x: (x["velocity_score"], x["article_count"]), reverse=True)

    # Extract Top 5 for each scope
    top_5_india = india_topics[:5]
    top_5_global = global_topics[:5]

    logger.info(f"Recorded {len(dynamic_topics)} total topics into Neon DB.")
    logger.info(f"Top 5 Global Trends: {[t['topic_name'] for t in top_5_global]}")
    logger.info(f"Top 5 India Trends: {[t['topic_name'] for t in top_5_india]}")

    return {
        "top_5_global": top_5_global,
        "top_5_india": top_5_india,
        "total_recorded": len(dynamic_topics)
    }
