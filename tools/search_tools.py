"""
Investigative Web Search Tool.
Gives agents autonomous research capability to verify rumors, find primary sources,
and validate breaking claims.
"""

import logging
from typing import List, Dict, Any
from duckduckgo_search import DDGS

logger = logging.getLogger("agent.tools.search")


def investigative_web_search(query: str, max_results: int = 4) -> str:
    """
    Executes a web search to corroborate facts, find official releases,
    or check original GitHub/arXiv sources.
    """
    logger.info(f"Agent executing investigative web search: '{query}'")
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                title = r.get("title", "")
                href = r.get("href", "")
                body = r.get("body", "")
                results.append(f"• Title: {title}\n  URL: {href}\n  Snippet: {body}")

        if not results:
            return "No external corroborating sources found."

        return "\n\n".join(results)
    except Exception as e:
        logger.error(f"Search failed for query '{query}': {e}")
        return f"Investigation search error: {str(e)}"
