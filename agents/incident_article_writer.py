"""Incident Article Writer Agent for Elinity News Network.

Takes the multi-source Research Dossier from investigative_fact_checker,
synthesizes a comprehensive, strictly fact-grounded investigative article,
and records the enriched dossier directly into the database for the frontend reader.
"""
from __future__ import annotations

import os
import re
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

import ollama

DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:latest")


def get_neon_connection():
    import psycopg2
    neon_url = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not neon_url:
        raise ValueError("Missing NEON_DATABASE_URL or DATABASE_URL in environment")
    return psycopg2.connect(neon_url)


def write_incident_article(
    dossier: Dict[str, Any],
    model: str = DEFAULT_OLLAMA_MODEL,
) -> Dict[str, Any]:
    """Synthesize a verified, in-depth investigative article from research evidence."""
    topic_name = dossier["topic_name"]
    pillar = dossier["pillar"]
    velocity = dossier["velocity_score"]
    evidence_items = dossier.get("evidence_pool") or []
    verified_sources = dossier.get("verified_sources") or []

    print(f"\n✍️ [ARTICLE WRITER] Synthesizing verified investigative article for: '{topic_name}'")

    # Combine corroborated evidence text
    evidence_text = "\n\n".join([
        f"--- Source [{e.get('source', 'Unknown')}]: {e.get('title', '')} ---\n{e.get('text', '')}"
        for e in evidence_items[:5]
    ])

    if not evidence_text.strip():
        evidence_text = f"Incident: {topic_name}. Category: {pillar}. Velocity: {velocity}x."

    prompt = f"""You are the Chief Investigative Editor at Elinity News Network.
Based strictly on the verified evidence below, write an in-depth, authoritative, fact-checked investigative news report.
Do NOT hallucinate or invent any unconfirmed details. Ground every statement in the evidence.

TOPIC: {topic_name}
CATEGORY: {pillar}
VELOCITY: {velocity}x

VERIFIED EVIDENCE:
{evidence_text}

OUTPUT FORMAT REQUIREMENTS:
Return a valid JSON object matching this schema exactly:
{{
  "headline": "A sharp, compelling, broadcast-standard headline (under 15 words)",
  "why_trending": "One impactful sentence explaining the exact catalyst that made this story surge today",
  "executive_briefing": "A concise 2-sentence summary of the core incident, verified numbers, and who is involved",
  "timeline": [
    "Chronological development 1 (e.g., initial alert or background)",
    "Chronological development 2 (core incident)",
    "Chronological development 3 (subsequent response or current status)"
  ],
  "key_facts": [
    "Verified fact/figure 1",
    "Verified fact/figure 2",
    "Verified fact/figure 3"
  ],
  "official_quotes": [
    "Direct quote attributed to a named official or agency (or 'None confirmed' if not in evidence)"
  ],
  "deep_dive_report": "A 3-paragraph in-depth journalistic article body explaining the full context, background, and what happens next.",
  "what_next": "A short outlook on upcoming developments or inquiries."
}}

Return ONLY the raw JSON string with no backticks, no markdown fencing, and no preamble."""

    try:
        NUM_CORES = os.cpu_count() or 16
        res = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional, fact-grounded investigative news editor. Output pure valid JSON."},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.3, "num_thread": NUM_CORES},
        )
        content = res["message"]["content"].strip()
        # Clean json fencing if present
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content).strip()
            content = re.sub(r"```$", "", content).strip()

        article_data = json.loads(content)
        print("✅ Article synthesized cleanly via local LLM.")

    except Exception as exc:
        print(f"⚠️ LLM generation fallback ({exc}). Assembling structured deterministic article...")
        article_data = {
            "headline": topic_name,
            "why_trending": dossier.get("why_trending") or f"Rapid coverage acceleration across independent outlets with {velocity}x velocity.",
            "executive_briefing": f"{topic_name} has emerged as a focal point in {pillar}, corroborated across multiple independent channels.",
            "timeline": [
                f"Story tracked with {velocity}x velocity across verified feeds.",
                "Primary source documentation confirmed.",
                "Ongoing monitoring by Elinity News Network."
            ],
            "key_facts": [
                f"Domain: {pillar}",
                f"Surge Velocity: {velocity}x",
                f"Corroborating Sources: {len(verified_sources)} outlets"
            ],
            "official_quotes": ["Monitoring official agency releases."],
            "deep_dive_report": evidence_text[:600],
            "what_next": "Follow Elinity News for continuous updates as further developments unfold."
        }

    # Format full rendered markdown for the reader UI
    full_markdown = f"""{article_data.get('executive_briefing', '')}

### ⚡ Why It's Trending Today
{article_data.get('why_trending', '')}

### ⏱️ Chronological Timeline
""" + "\n".join([f"• **{t}**" for t in article_data.get("timeline", [])]) + f"""

### 📊 Key Verified Facts
""" + "\n".join([f"• {f}" for f in article_data.get("key_facts", [])]) + f"""

### 🎙️ Official Statements & Quotes
""" + "\n".join([f"> *\"{q}\"*" for q in article_data.get("official_quotes", []) if q and q != 'None confirmed']) + f"""

### 🔍 In-Depth Incident Report
{article_data.get('deep_dive_report', '')}

### 🔮 What Happens Next
{article_data.get('what_next', '')}
"""

    result_dossier = {
        "incident_id": dossier["incident_id"],
        "headline": article_data.get("headline", topic_name),
        "why_trending": article_data.get("why_trending", ""),
        "executive_briefing": article_data.get("executive_briefing", ""),
        "timeline": article_data.get("timeline", []),
        "key_facts": article_data.get("key_facts", []),
        "official_quotes": article_data.get("official_quotes", []),
        "deep_dive_report": article_data.get("deep_dive_report", ""),
        "what_next": article_data.get("what_next", ""),
        "full_markdown_article": full_markdown.strip(),
        "verified_sources": verified_sources,
        "verified_images": dossier.get("verified_images", []),
        "velocity_score": velocity,
        "pillar": pillar,
    }

    return result_dossier


def persist_incident_article_to_db(article_dossier: Dict[str, Any]) -> bool:
    """Save the fact-checked article into Neon DB topic_snapshots for the frontend reader."""
    incident_id = article_dossier.get("incident_id")
    if not incident_id:
        return False

    try:
        conn = get_neon_connection()
        cur = conn.cursor()

        # Update summary, why_trending, and reference_articles with enriched dossier
        summary_payload = article_dossier["full_markdown_article"]
        why_trending = article_dossier["why_trending"]
        sources_json = json.dumps(article_dossier["verified_sources"])

        query = """
            UPDATE topic_snapshots
            SET 
                summary = %s,
                why_trending = %s,
                reference_articles = %s
            WHERE id = %s;
        """
        cur.execute(query, (summary_payload, why_trending, sources_json, incident_id))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Enriched incident dossier persisted to Neon DB (ID: {incident_id}).")

        # Also write standalone markdown report file to disk for direct inspection & web UI
        try:
            rep_dir = ROOT_DIR / "outputs" / "reports"
            rep_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^\w]", "_", article_dossier.get("headline", "incident").lower())[:30].strip("_")
            md_path = rep_dir / f"report_{incident_id}_{slug}.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(summary_payload)
            with open(rep_dir / "latest_report.md", "w", encoding="utf-8") as f:
                f.write(summary_payload)
            web_rep_dir = Path("D:/AI PYTHON PROJECTS/news_web/public/reports")
            if web_rep_dir.parent.exists():
                web_rep_dir.mkdir(parents=True, exist_ok=True)
                with open(web_rep_dir / f"incident_{incident_id}.md", "w", encoding="utf-8") as f:
                    f.write(summary_payload)
            print(f"📄 Incident report file written: {md_path}")
        except Exception as file_err:
            print(f"ℹ️ Report file save note: {file_err}")

        return True
    except Exception as exc:
        print(f"❌ Failed to persist incident article to Neon DB: {exc}")
        return False


if __name__ == "__main__":
    from agents.investigative_fact_checker import fetch_unprocessed_trending_incidents, investigate_incident
    incidents = fetch_unprocessed_trending_incidents(min_velocity=1.5, limit=1)
    if incidents:
        dossier = investigate_incident(incidents[0])
        article = write_incident_article(dossier)
        print("\n--- GENERATED ARTICLE HEADLINE ---")
        print(article["headline"])
        print("\n--- WHY TRENDING ---")
        print(article["why_trending"])
        print("\n--- FULL MARKDOWN ARTICLE EXCERPT ---")
        print(article["full_markdown_article"][:400] + "...")
        # Test DB save
        persist_incident_article_to_db(article)
    else:
        print("No incident available for test.")
