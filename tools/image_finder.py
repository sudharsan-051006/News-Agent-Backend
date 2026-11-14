"""
Autonomous Internet Image Finder for News Articles and Trends.
1. Searches Wikimedia Commons for real-world entities, persons, organizations, and landmarks.
2. Searches Image Search API (Unsplash search via Render microservice) for concepts, topics, and events.
3. Automatically returns verified, high-resolution direct image URLs.
"""

import logging
import requests
from typing import Optional, List

logger = logging.getLogger("agent.tools.image_finder")

RENDER_IMAGE_API_URL = "https://image-search-errf.onrender.com/search"
RENDER_IMAGE_API_KEY = "ECbU4IOTmw-xrZzb2BPvmO2IYJljIuoqYFKDfaMPKSM"


def search_wikimedia(query: str) -> Optional[str]:
    """Searches Wikipedia/Wikimedia Commons for a real photo of the entity/topic."""
    if not query or len(query.strip()) < 3:
        return None
    try:
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "prop": "pageimages",
            "generator": "search",
            "gsrsearch": query.strip()[:80],
            "gsrlimit": 1,
            "pithumbsize": 1200
        }
        headers = {"User-Agent": "AI-NewsRadar-Agent/2.0 (editorial-research)"}
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code == 200:
            pages = resp.json().get("query", {}).get("pages", {})
            for _, page in pages.items():
                if "thumbnail" in page and page["thumbnail"].get("source"):
                    img_src = page["thumbnail"]["source"]
                    # Filter out tiny icons or math SVGs
                    if not any(bad in img_src.lower() for bad in ["symbol", "ambox", "question_mark"]):
                        return img_src
    except Exception as e:
        logger.debug(f"Wikimedia search skipped for '{query}': {e}")
    return None


def search_render_image_api(query: str) -> Optional[str]:
    """Queries the Render Image Search API (Unsplash search)."""
    if not query or len(query.strip()) < 3:
        return None
    try:
        headers = {"Content-Type": "application/json"}
        if RENDER_IMAGE_API_KEY:
            headers["X-API-Key"] = RENDER_IMAGE_API_KEY

        resp = requests.post(
            RENDER_IMAGE_API_URL,
            headers=headers,
            json={"sentence": query.strip()[:100], "count": 1},
            timeout=8
        )
        if resp.status_code == 200:
            images = resp.json().get("images", [])
            if images and images[0].get("image_url"):
                return images[0]["image_url"]
    except Exception as e:
        logger.debug(f"Render image search skipped for '{query}': {e}")
    return None


def find_internet_image(topic_name: str, keywords: Optional[List[str]] = None) -> Optional[str]:
    """
    Autonomously searches the internet for a highly relevant image URL.
    1. Tries Wikimedia Commons with keywords (e.g. 'Sonam Wangchuk' or 'Jensen Huang').
    2. Tries Wikimedia Commons with the clean topic title.
    3. Tries the Render Unsplash Image Search API with keywords or clean title.
    Returns: A direct, usable image URL or None.
    """
    clean_topic = topic_name.strip()
    
    # Tier 1: Try Wikimedia with main keywords (best for real people, places, orgs)
    if keywords:
        kw_phrase = " ".join([k for k in keywords if len(k) > 2][:2])
        if kw_phrase:
            wiki_img = search_wikimedia(kw_phrase)
            if wiki_img:
                logger.info(f"🖼️ Found Wikimedia image for '{kw_phrase}': {wiki_img[:60]}...")
                return wiki_img

    # Tier 2: Try Wikimedia with full topic title
    wiki_img = search_wikimedia(clean_topic)
    if wiki_img:
        logger.info(f"🖼️ Found Wikimedia image for '{clean_topic}': {wiki_img[:60]}...")
        return wiki_img

    # Tier 3: Try Render Unsplash search with keywords
    if keywords:
        search_query = " ".join([k for k in keywords if len(k) > 2][:3])
        api_img = search_render_image_api(search_query)
        if api_img:
            logger.info(f"🖼️ Found Unsplash image for '{search_query}': {api_img[:60]}...")
            return api_img

    # Tier 4: Try Render Unsplash search with topic title
    api_img = search_render_image_api(clean_topic[:60])
    if api_img:
        logger.info(f"🖼️ Found Unsplash image for '{clean_topic[:40]}': {api_img[:60]}...")
        return api_img

    return None
