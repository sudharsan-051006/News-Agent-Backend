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
    "Sports": "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "Entertainment & Movies": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=1200&q=80",
    "Science & Environment": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80",
    "General News": "https://images.unsplash.com/photo-1504711434969-e33886168f5c?auto=format&fit=crop&w=1200&q=80"
}

GENERIC_STOPWORDS = {
    "news", "today", "report", "reports", "reported", "reporting",
    "says", "said", "saying", "amid", "with", "after", "into", "from", "over",
    "more", "first", "live", "update", "updates", "week", "year", "time", "back", "next",
    "will", "have", "been", "being", "their", "there", "about", "could", "would",
    "national", "world", "india", "indian", "state", "centre", "central",
    "minister", "chief", "govt", "government", "leader", "party",
    "general", "public", "people", "daily", "video", "photos", "watch", "read",
    "ahead", "case", "high", "down", "post", "take", "takes", "taking", "taken",
    "make", "makes", "making", "made", "affairs", "politics", "business",
    "mumbai", "delhi", "chennai", "kolkata", "hyderabad", "bengaluru", "punjab", "kerala", "bhopal",
    "court", "police", "arrest", "arrested", "arrests", "held", "calls", "called",
    "urges", "urged", "seeks", "sought", "claims", "claimed", "tells", "told"
}

BANNED_TOPIC_NAMES = {
    "india politics", "india affairs", "general news", "global news",
    "cybersecurity", "entertainment", "india business", "world news",
    "politics", "business", "breaking news", "daily news"
}


def extract_significant_tokens(text: str) -> set:
    """Extracts lowercase tokens of length >= 3 excluding generic news stop words."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    return {w for w in words if w not in GENERIC_STOPWORDS}


def are_topics_similar(t1: str, t2: str) -> bool:
    """
    Determines if two topic titles represent the exact same story/event.
    Uses Szymkiewicz-Simpson overlap coefficient and Jaccard token similarity.
    """
    s1 = extract_significant_tokens(t1)
    s2 = extract_significant_tokens(t2)
    if not s1 or not s2:
        return False
    inter = s1 & s2
    jaccard = len(inter) / len(s1 | s2) if (s1 | s2) else 0.0
    min_len = min(len(s1), len(s2))
    overlap = len(inter) / min_len if min_len > 0 else 0.0
    # Match if high Jaccard OR if the smaller title's keywords are >= 50% contained in the other with at least 2 tokens
    return jaccard >= 0.35 or (overlap >= 0.5 and len(inter) >= 2)


def is_article_relevant_to_topic(topic_name: str, article_title: str) -> bool:
    """
    Strict validation: An article is ONLY relevant to a topic if it shares
    at least TWO specific story keywords. Discards incidental 1-word overlaps (e.g. 'calls', 'mumbai').
    """
    t_tok = extract_significant_tokens(topic_name)
    a_tok = extract_significant_tokens(article_title)
    if not t_tok or not a_tok:
        return False
    return len(t_tok & a_tok) >= 2


def select_best_image_for_topic(topic_name: str, articles_list: List[Dict[str, Any]], keywords: List[str] = None) -> str:
    """
    Strict image selection: Ensures a topic gets an image from an article
    whose title actually matches the topic name, preventing photo/headline mismatches!
    Falls back to Wikimedia / web image search if articles have no relevant image.
    """
    t_tok = extract_significant_tokens(topic_name)
    best_img = ""
    best_score = 0
    for a in articles_list:
        img = a.get("image_url")
        if not img or not img.startswith("http"):
            continue
        a_tok = extract_significant_tokens(a.get("title", ""))
        score = len(t_tok & a_tok)
        if score > best_score:
            best_score = score
            best_img = img

    if best_img and best_score >= 1:
        return best_img

    # Fallback to web search for the specific topic headline
    web_img = find_internet_image(topic_name, keywords or [])
    if web_img:
        return web_img

    # If only 1 article exists in the cluster and it has an image, use it
    if len(articles_list) == 1 and articles_list[0].get("image_url"):
        return articles_list[0]["image_url"]

    return ""


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
    Enforces strict event-level cohesion and prunes unrelated articles.
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
1. STRICT EVENT-LEVEL CLUSTERING:
   - Multiple headlines should ONLY be grouped together if they report on the EXACT SAME SPECIFIC STORY OR EVENT (e.g. multiple outlets covering 'SpaceX Starship Booster Catch', 'OpenAI Claude Lawsuit', or 'Delhi Air Quality Hazard').
   - NEVER create broad, vague buckets like 'India Politics', 'India Affairs', 'General News', 'Global News', 'Cybersecurity', or 'Entertainment'. Every topic name MUST describe the specific event (e.g. 'President Murmu and PM Modi Greet Jharkhand on Foundation Day', 'Italian Antitrust Fines Meta Over Photos').
   - If an article is reporting on a standalone story, KEEP IT AS ITS OWN SINGLE-ARTICLE TOPIC (with article_ids containing just that 1 ID). NEVER dump unrelated headlines into a single topic.
2. EXACT ARTICLE IDS: The "article_ids" array MUST contain the EXACT integer "id" values (1 to {len(sample_headlines)}) corresponding to the headlines covering that specific event.
3. "topic_name": Specific, descriptive 3-7 word event title (e.g. 'Delhi Air Quality Reaches Hazardous AQI', 'SpaceX Starship Caught by Launchpad Arms', 'Uttarakhand MLA Throws Microphone in Assembly').
4. "pillar": Dynamically identify and assign the natural category based strictly on the story:
   - "Technology & AI"
   - "Geopolitics & Security"
   - "India Affairs"
   - "Finance & Markets"
   - "Sports"
   - "Entertainment & Movies"
   - "Science & Environment"
5. "scope": Classify as "INDIA" or "GLOBAL".
6. "why_trending": 1-2 clear sentences explaining the EXACT CATALYST or EVENT that occurred today.
7. "summary": 1-2 sentence objective factual summary.
8. "keywords": 3-5 core keywords specific to the event.
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
            logger.info(f"Successfully discovered {len(clusters)} raw event categories from LLM.")
            
            # Map back article data to each cluster (supporting 1-based and 0-based LLM quirks)
            id_to_article = {idx + 1: a for idx, a in enumerate(valid_articles)}
            
            processed_clusters = []
            used_article_guids = set()

            for c in clusters:
                t_name = c.get("topic_name", "").strip()
                assigned = []
                for aid in c.get("article_ids", []):
                    art = id_to_article.get(aid) or (valid_articles[aid] if 0 <= aid < len(valid_articles) else None)
                    if art and art.get("guid") and art["guid"] not in [x.get("guid") for x in assigned]:
                        assigned.append(art)
                
                # If topic name is generic (e.g. "India Politics"), rename using primary article's title
                if t_name.lower() in BANNED_TOPIC_NAMES or len(extract_significant_tokens(t_name)) < 2:
                    if assigned:
                        t_name = assigned[0].get("title", t_name)[:65]
                        c["topic_name"] = t_name

                # Strict per-article verification:
                # Every article in assigned MUST match the topic's specific story!
                verified_articles = []
                for a in assigned:
                    if is_article_relevant_to_topic(t_name, a.get("title", "")):
                        verified_articles.append(a)
                        used_article_guids.add(a.get("guid"))
                    else:
                        logger.warning(f"Pruned unrelated article '{a.get('title')}' from topic '{t_name}'")

                # If no articles passed verification, realign with the single best matching article
                if not verified_articles and valid_articles:
                    best_art = None
                    best_score = 0
                    t_tok = extract_significant_tokens(t_name)
                    for a in valid_articles:
                        a_tok = extract_significant_tokens(a.get("title", ""))
                        score = len(t_tok & a_tok)
                        if score > best_score:
                            best_score = score
                            best_art = a
                    if best_art and best_score >= 1:
                        verified_articles = [best_art]
                        used_article_guids.add(best_art.get("guid"))

                if verified_articles:
                    c["articles"] = verified_articles
                    c["article_count"] = len(verified_articles)
                    processed_clusters.append(c)

            # Intra-run deduplication: Merge clusters reporting on the same event
            merged_clusters = []
            for c in processed_clusters:
                merged = False
                for existing in merged_clusters:
                    if are_topics_similar(c.get("topic_name", ""), existing.get("topic_name", "")):
                        logger.info(f"Merging duplicate clusters: '{c.get('topic_name')}' into '{existing.get('topic_name')}'")
                        existing_guids = {a.get("guid") for a in existing.get("articles", [])}
                        for a in c.get("articles", []):
                            if a.get("guid") and a.get("guid") not in existing_guids:
                                existing["articles"].append(a)
                                existing_guids.add(a.get("guid"))
                        existing["article_count"] = len(existing["articles"])
                        # Retain the more descriptive title
                        if len(c.get("topic_name", "")) > len(existing.get("topic_name", "")):
                            existing["topic_name"] = c.get("topic_name")
                        merged = True
                        break
                if not merged:
                    merged_clusters.append(c)

            # Add any valid articles that were unassigned or pruned as clean 1-mention seed topics
            for a in valid_articles:
                if a.get("guid") and a["guid"] not in used_article_guids:
                    # Check if already covered by an existing cluster
                    already_covered = False
                    for mc in merged_clusters:
                        if is_article_relevant_to_topic(mc.get("topic_name", ""), a.get("title", "")):
                            if a["guid"] not in {x.get("guid") for x in mc.get("articles", [])}:
                                mc["articles"].append(a)
                                mc["article_count"] = len(mc["articles"])
                            already_covered = True
                            break
                    if not already_covered:
                        title = a.get("title", "")
                        is_india = any(w in title.lower() for w in ["india", "delhi", "mumbai", "modi", "rupee", "sebi"])
                        merged_clusters.append({
                            "topic_name": title[:65],
                            "pillar": a.get("primary_topic") or ("India Affairs" if is_india else "General News"),
                            "scope": "INDIA" if is_india else "GLOBAL",
                            "why_trending": f"Breaking report covered by {a.get('feed_name', 'major news feeds')}.",
                            "summary": title,
                            "keywords": list(extract_significant_tokens(title))[:4],
                            "article_count": 1,
                            "articles": [a]
                        })
                        used_article_guids.add(a["guid"])

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
            "topic_name": title[:65],
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
    2. Stores EVERY topic into Neon DB with strictly matched images, why_trending, pillar, and reference links.
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
        keywords = t.get("keywords", [])
        summary = t.get("summary", "")
        articles_list = t.get("articles", [])
        count = len(articles_list) if articles_list else t.get("article_count", 1)

        # Strictly select image that matches the headline content
        image_url = select_best_image_for_topic(topic_name, articles_list, keywords)

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
