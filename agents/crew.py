"""
Multi-Agent Trend Radar Crew (CrewAI).
Supports:
1. Dynamic Zero-Shot Event Categorization.
2. Top 5 Global + Top 5 India Trending Topics.
3. Resumable step-by-step execution with database checkpoints.
4. Strict anti-hallucination factual grounding.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from llm_adapter import get_crewai_llm
from tools.search_tools import investigative_web_search

logger = logging.getLogger("agent.crew")


@tool("Investigative Web Search Tool")
def search_tool(query: str) -> str:
    """Useful to search the web to corroborate breaking news, find official links, or verify claims."""
    return investigative_web_search(query)


def get_agents():
    """Factory creating the 4 cognitive agent roles."""
    llm = get_crewai_llm()

    scout = Agent(
        role="Lead News & Anomaly Scout",
        goal="Select and prioritize the Top 5 Global and Top 5 India trending storylines based on real velocity data.",
        backstory="You are an elite intelligence researcher who works strictly with factual evidence. You ground your findings entirely in today's real news.",
        llm=llm,
        verbose=True
    )

    investigator = Agent(
        role="Autonomous Investigative Journalist",
        goal="Corroborate facts for breaking stories using search tools when necessary.",
        backstory="You verify claims, locate primary sources, and confirm authenticity using web search.",
        tools=[search_tool],
        llm=llm,
        verbose=True
    )

    editor = Agent(
        role="Executive Newsletter Editor",
        goal="Craft an executive intelligence briefing showcasing the Top 5 Global and Top 5 India Trending Topics with 'Why It Matters'.",
        backstory="You write high-signal executive newsletters for top leaders, grounding every word strictly in today's real news.",
        llm=llm,
        verbose=True
    )

    critic = Agent(
        role="Managing Editor & Fact-Check Gatekeeper",
        goal="Audit the briefing against strict standards: ensure 100% factual grounding in today's news and decide GO/NO_GO.",
        backstory="You reject any draft containing outdated or fabricated stories. You only approve briefings backed by today's real feed items.",
        llm=llm,
        verbose=True
    )

    return scout, investigator, editor, critic


def format_top_trends_for_prompt(trend_data: Dict[str, Any]) -> str:
    """Formats Top 5 Global and Top 5 India trends for agent prompt context."""
    global_list = trend_data.get("top_5_global", [])
    india_list = trend_data.get("top_5_india", [])

    output = []
    output.append("=== TOP 5 GLOBAL TRENDING TOPICS (Ranked by Momentum) ===")
    for idx, t in enumerate(global_list, 1):
        titles_urls = "\n".join([f"    • {a.get('title')} ({a.get('url')})" for a in t.get("articles", [])[:3]])
        output.append(f"{idx}. {t['topic_name']} [Trend: {t['trend_type']}, Velocity: {t['velocity_score']}x]")
        output.append(f"   Summary: {t['summary']}")
        if titles_urls:
            output.append(f"   Real Articles:\n{titles_urls}")

    output.append("\n=== TOP 5 INDIA TRENDING TOPICS (Ranked by Momentum) ===")
    for idx, t in enumerate(india_list, 1):
        titles_urls = "\n".join([f"    • {a.get('title')} ({a.get('url')})" for a in t.get("articles", [])[:3]])
        output.append(f"{idx}. {t['topic_name']} [Trend: {t['trend_type']}, Velocity: {t['velocity_score']}x]")
        output.append(f"   Summary: {t['summary']}")
        if titles_urls:
            output.append(f"   Real Articles:\n{titles_urls}")

    return "\n".join(output)


# =====================================================================
# Step-by-Step Resumable Execution Functions
# =====================================================================

def execute_scout_step(trend_data: Dict[str, Any]) -> str:
    """Step 1: Analyzes and contextualizes Top 5 Global + Top 5 India trends."""
    scout, _, _, _ = get_agents()
    today_str = datetime.now().strftime("%B %d, %Y")
    formatted_trends = format_top_trends_for_prompt(trend_data)

    task = Task(
        description=f"""
        Today is {today_str}.
        Review the dynamic trending topics discovered from today's feeds:
        
        {formatted_trends}
        
        CRITICAL GROUNDING INSTRUCTIONS:
        1. Contextualize the Top 5 Global and Top 5 India trending topics.
        2. Verify that all 10 storylines represent real current news from today's data.
        3. Flag any specific breaking story (e.g. IPOs, wars, natural disasters, treaties) that warrants quick primary source verification.
        """,
        expected_output="Curated breakdown of the Top 5 Global and Top 5 India storylines with verification notes.",
        agent=scout
    )
    crew = Crew(agents=[scout], tasks=[task], verbose=True)
    return str(crew.kickoff())


def execute_investigator_step(scout_findings: str) -> str:
    """Step 2: Autonomously investigates prioritized topics using search tool."""
    _, investigator, _, _ = get_agents()

    task = Task(
        description=f"""
        Review the Scout's curated storylines:
        {scout_findings}
        
        For any major breaking story or flagged claim:
        1. Verify the core facts, names, and organizations.
        2. Ensure real URLs are preserved for reader reference.
        """,
        expected_output="Verified facts and supporting context for today's selected stories.",
        agent=investigator
    )
    crew = Crew(agents=[investigator], tasks=[task], verbose=True)
    return str(crew.kickoff())


def execute_editor_step(investigator_evidence: str) -> str:
    """Step 3: Drafts the executive briefing with Top 5 Global and Top 5 India trends."""
    _, _, editor, _ = get_agents()
    today_str = datetime.now().strftime("%B %d, %Y")

    task = Task(
        description=f"""
        Today is {today_str}.
        Using the verified evidence provided below:
        {investigator_evidence}
        
        Draft the complete Daily Trend Radar email briefing for {today_str}.
        
        MANDATORY STRUCTURE:
        1. **Executive Trend Briefing**: 2-sentence macro synthesis of the predominant shifts today.
        
        2. **🌍 TOP 5 GLOBAL TRENDING STORIES**:
           For each of the 5 global topics:
           • **[Category Name]** with Trend Badge (e.g. [🚀 BREAKOUT +X%], [🌟 EMERGING], or [🔄 EVOLVING])
           • Headline with direct source link
           • 2-sentence breakdown of what happened
           • Bold **Why It Matters** strategic takeaway
        
        3. **🇮🇳 TOP 5 INDIA TRENDING STORIES**:
           For each of the 5 India topics:
           • **[Category Name]** with Trend Badge (e.g. [🚀 BREAKOUT +X%], [🌟 EMERGING], or [🔄 EVOLVING])
           • Headline with direct source link
           • 2-sentence breakdown of what happened
           • Bold **Why It Matters** strategic takeaway
        
        STRICT RULES:
        - Exactly 5 Global and 5 India stories.
        - Do NOT include old news from 2023. Every story must come from the provided evidence.
        """,
        expected_output=f"A complete publication-ready markdown briefing for {today_str} featuring exactly 5 Global and 5 India trending stories with 'Why It Matters' bullets.",
        agent=editor
    )
    crew = Crew(agents=[editor], tasks=[task], verbose=True)
    return str(crew.kickoff())


def execute_critic_step(draft_briefing: str) -> str:
    """Step 4: Performs self-reflection audit and outputs GO / NO_GO decision."""
    _, _, _, critic = get_agents()
    today_str = datetime.now().strftime("%B %d, %Y")

    task = Task(
        description=f"""
        Perform a rigorous editorial critique of the following draft briefing for {today_str}:
        {draft_briefing}
        
        1. Grounding Check: Are the stories real and from today ({today_str})? (Reject any mention of 2023).
        2. Scope Check: Does it have both Top 5 Global and Top 5 India stories?
        3. Signal Check: Are the 'Why It Matters' points sharp and actionable?
        4. Provide your FINAL DECISION:
           - If Score >= 8.5: 'DECISION: GO'
           - If substandard: 'DECISION: NO_GO'
        5. Output your critique review, score, and the final approved briefing.
        """,
        expected_output="Critique review, score, decision (GO/NO_GO), and the approved briefing text.",
        agent=critic
    )
    crew = Crew(agents=[critic], tasks=[task], verbose=True)
    return str(crew.kickoff())
