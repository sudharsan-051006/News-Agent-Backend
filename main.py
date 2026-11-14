"""
Main Orchestrator & Entry Point for AI News Trend Radar Agent.

Schedules:
1. Every 4 Hours: Background Trend Analysis & RSS Ingestion (No email, updates Neon DB).
2. Every Day at 07:00 AM: Executive Trend Briefing & Email Dispatch (4-Agent Crew with Checkpoints).

CLI Commands:
- python main.py --run-now      : Run the 7 AM daily email briefing immediately.
- python main.py --sample-now   : Run the 4-hour trend analysis & DB sampling immediately.
- python main.py --force        : Clear checkpoints and run 7 AM briefing from scratch.
- python main.py --daemon       : Start the 4-hour + daily 7:00 AM background scheduler.
"""

import sys
import argparse
import logging
from collections import Counter
from datetime import datetime
from typing import List, Dict, Any
from apscheduler.schedulers.blocking import BlockingScheduler

from config import settings
from database import (
    init_db, 
    seed_default_feeds, 
    get_active_feeds, 
    get_recent_articles,
    get_checkpoint,
    save_checkpoint,
    clear_today_checkpoints,
    log_audit_decision
)
from tools.rss_tools import fetch_and_clean_feed
from tools.trend_calculator import discover_dynamic_topics, process_and_rank_trends
from agents.crew import (
    execute_scout_step,
    execute_investigator_step,
    execute_editor_step,
    execute_critic_step
)
from email_service import send_trend_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("agent.main")


def classify_topics(articles: List[Dict[str, Any]]) -> Dict[str, int]:
    """Classifies articles into the 4 key news domains."""
    topic_counter = Counter()
    for a in articles:
        title_lower = a.get("title", "").lower()
        if any(w in title_lower for w in ["india", "delhi", "mumbai", "modi", "parliament", "bjp", "congress", "supreme court", "rupee", "isro", "bharat", "cabinet", "bengaluru"]):
            topic_counter["India Affairs & Governance"] += 1
        elif any(w in title_lower for w in ["war", "treaty", "sanction", "china", "russia", "ukraine", "nato", "un", "diplomacy", "israel", "gaza", "military", "geopolitic", "taiwan", "iran", "pentagon"]):
            topic_counter["Geopolitics & Global Security"] += 1
        elif any(w in title_lower for w in ["market", "stock", "nifty", "sensex", "fed", "inflation", "rbi", "rate", "bank", "invest", "economy", "crypto", "bitcoin", "earnings", "shares"]):
            topic_counter["Finance, Markets & Economy"] += 1
        elif any(w in title_lower for w in ["ai", "llm", "model", "gpt", "agent", "deepmind", "openai", "chip", "nvidia", "hardware", "semiconductor", "tech", "software"]):
            topic_counter["Technology & Artificial Intelligence"] += 1
        else:
            topic_counter["Global Industry & Society"] += 1
    return dict(topic_counter)


def job_sample_and_update_trends():
    """
    Background Job 1: Runs every 4 hours.
    Polls feeds (10 latest per feed), deduplicates, and updates Neon DB snapshots.
    Does NOT send email (only tracks rolling time-series momentum).
    """
    logger.info("🕒 [4-HOUR TREND SAMPLING] Ingesting feeds and updating 6-day baseline...")
    try:
        init_db()
        seed_default_feeds()
    except Exception as e:
        logger.error(f"Database error during 4-hour sampling: {e}")
        return

    active_feeds = get_active_feeds()
    all_new = []
    for feed in active_feeds:
        articles = fetch_and_clean_feed(feed["id"], feed["url"])
        all_new.extend(articles)

    logger.info(f"Ingested {len(all_new)} brand-new articles in this 4-hour window.")

    # Discover dynamic event categories and compute velocity across 24h window
    recent_articles = get_recent_articles(hours=24)
    logger.info(f"Discovering dynamic topics across {len(recent_articles)} articles...")
    dynamic_topics = discover_dynamic_topics(recent_articles)
    trend_results = process_and_rank_trends(dynamic_topics)
    
    logger.info(f"Recorded {trend_results['total_recorded']} dynamic topics into Neon DB.")
    logger.info("🕒 [4-HOUR TREND SAMPLING FINISHED] All topics saved to DB. (No email dispatched).")


def run_trend_radar_pipeline(force: bool = False):
    """
    Job 2: Runs once a day at 07:00 AM.
    Discovers dynamic event categories, ranks Top 5 Global + Top 5 India trends,
    executes the 4-Agent Crew with checkpoints, and dispatches the daily email.
    """
    logger.info("==============================================================")
    logger.info("🌅 [DAILY 7:00 AM BRIEFING] Launching Multi-Agent Trend Radar Pipeline")
    logger.info("==============================================================")

    # Step 1: Initialize Neon DB
    try:
        init_db()
        seed_default_feeds()
    except Exception as e:
        logger.error(f"Failed to connect or initialize Neon DB: {e}")
        return

    if force:
        logger.info("⚡ [FORCE MODE] Clearing today's checkpoints for a fresh run...")
        clear_today_checkpoints()

    # Step 2: Ensure latest feeds are polled before generating briefing
    active_feeds = get_active_feeds()
    for feed in active_feeds:
        fetch_and_clean_feed(feed["id"], feed["url"])

    articles_24h = get_recent_articles(hours=24)
    logger.info(f"Analyzing {len(articles_24h)} articles from the 24-hour window.")

    if not articles_24h:
        logger.info("No articles found in 24h window. Suppressing run.")
        log_audit_decision(
            decision="SUPPRESSED_LOW_SIGNAL",
            critic_score=10.0,
            critic_feedback="No articles found in 24h window."
        )
        return

    # Step 3: Discover dynamic topics on-the-fly and save ALL to Neon DB
    logger.info("Detecting dynamic event categories across articles...")
    dynamic_topics = discover_dynamic_topics(articles_24h)
    trend_results = process_and_rank_trends(dynamic_topics)
    logger.info(f"Saved {trend_results['total_recorded']} total categories into Neon DB.")

    # =====================================================================
    # RESUMABLE STEP-BY-STEP AGENT DELIBERATION
    # =====================================================================

    # --- Step 4.1: Scout Agent ---
    scout_findings = get_checkpoint("SCOUT")
    if not scout_findings:
        logger.info("🚀 Running Agent 1: Lead News Scout (Top 5 Global + Top 5 India)...")
        scout_findings = execute_scout_step(trend_results)
        save_checkpoint("SCOUT", scout_findings)
        logger.info("💾 Saved Step 1 (SCOUT) checkpoint to Neon DB.")
    else:
        logger.info("⚡ [RESUMED] Step 1 (SCOUT) loaded from saved checkpoint.")

    # --- Step 4.2: Investigative Researcher Agent ---
    investigator_evidence = get_checkpoint("INVESTIGATOR")
    if not investigator_evidence:
        logger.info("🚀 Running Agent 2: Autonomous Investigative Researcher (ReAct search)...")
        investigator_evidence = execute_investigator_step(scout_findings)
        save_checkpoint("INVESTIGATOR", investigator_evidence)
        logger.info("💾 Saved Step 2 (INVESTIGATOR) checkpoint to Neon DB.")
    else:
        logger.info("⚡ [RESUMED] Step 2 (INVESTIGATOR) loaded from saved checkpoint.")

    # --- Step 4.3: Chief Editor Agent ---
    editor_draft = get_checkpoint("EDITOR")
    if not editor_draft:
        logger.info("🚀 Running Agent 3: Chief Editorial Synthesizer...")
        editor_draft = execute_editor_step(investigator_evidence)
        save_checkpoint("EDITOR", editor_draft)
        logger.info("💾 Saved Step 3 (EDITOR) checkpoint to Neon DB.")
    else:
        logger.info("⚡ [RESUMED] Step 3 (EDITOR) loaded from saved checkpoint.")

    # --- Step 4.4: Critic Gatekeeper Agent ---
    critic_verdict = get_checkpoint("CRITIC")
    if not critic_verdict:
        logger.info("🚀 Running Agent 4: Critic & Quality Gatekeeper (Self-Reflection)...")
        critic_verdict = execute_critic_step(editor_draft)
        save_checkpoint("CRITIC", critic_verdict)
        logger.info("💾 Saved Step 4 (CRITIC) checkpoint to Neon DB.")
    else:
        logger.info("⚡ [RESUMED] Step 4 (CRITIC) loaded from saved checkpoint.")

    # =====================================================================
    # Step 5: Autonomous Go / No-Go Decision Gate & Email Dispatch
    # =====================================================================
    top_global = trend_results.get("top_5_global", [])
    top_india = trend_results.get("top_5_india", [])
    top_trend_name = top_global[0]["topic_name"] if top_global else (top_india[0]["topic_name"] if top_india else "Emerging Shifts")
    
    critic_upper = (critic_verdict or "").upper()
    has_go = (
        "DECISION: GO" in critic_upper
        or "DECISION:GO" in critic_upper
        or "VERDICT: GO" in critic_upper
        or "STATUS: APPROVED" in critic_upper
        or "DECISION: APPROVE" in critic_upper
    )
    is_go = has_go or not settings.ENABLE_SIGNIFICANCE_GATE

    if is_go:
        logger.info("Autonomous Gatekeeper APPROVED dispatch (Decision: GO).")
        subject = f"[Daily Trend Radar] {top_trend_name} & Emerging Shifts — {datetime.now().strftime('%b %d')}"
        exec_summary = f"Macro intelligence analysis across {len(articles_24h)} stories over the last 24h against our 6-day baseline."
        
        # Clean up Markdown linebreaks for HTML cards
        body_html = f"<div class='card' style='line-height:1.6;'>{editor_draft.replace(chr(10), '<br>')}</div>"
        
        delivered = send_trend_email(subject, exec_summary, body_html)
        log_audit_decision(
            decision="DISPATCHED" if delivered else "DELIVERY_FAILED",
            critic_score=9.0,
            critic_feedback=critic_verdict[:500],
            email_subject=subject,
            top_trend=top_trend_name
        )
    else:
        logger.warning("Autonomous Gatekeeper SUPPRESSED dispatch (Decision: NO_GO). News is flat or below threshold.")
        logger.info(f"Critic Gatekeeper Feedback:\n{critic_verdict}")
        log_audit_decision(
            decision="SUPPRESSED_LOW_SIGNAL",
            critic_score=7.0,
            critic_feedback=critic_verdict[:500],
            top_trend=top_trend_name
        )

    logger.info("🌅 [DAILY BRIEFING PIPELINE FINISHED]")


def start_scheduler():
    """Runs APScheduler: Polling & Trend analysis every 4 hours, Email at 7:00 AM daily."""
    scheduler = BlockingScheduler()

    # Job 1: Every 4 Hours background trend tracking
    scheduler.add_job(
        job_sample_and_update_trends,
        'interval',
        hours=settings.SAMPLING_INTERVAL_HOURS,
        id='four_hour_sampling_job'
    )

    # Job 2: Daily 07:00 AM Email Briefing
    scheduler.add_job(
        run_trend_radar_pipeline,
        'cron',
        hour=settings.DAILY_RUN_HOUR,
        minute=settings.DAILY_RUN_MINUTE,
        id='daily_7am_briefing_job'
    )

    logger.info("==============================================================")
    logger.info(f"⚡ Scheduler Active:")
    logger.info(f"  1. Trend Sampling & DB Ingestion: Every {settings.SAMPLING_INTERVAL_HOURS} hours")
    logger.info(f"  2. Daily Email Briefing: Every morning at {settings.DAILY_RUN_HOUR:02d}:{settings.DAILY_RUN_MINUTE:02d} AM")
    logger.info("==============================================================")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI News Trend Radar Agent")
    parser.add_argument("--run-now", action="store_true", help="Execute the 7:00 AM daily email briefing immediately.")
    parser.add_argument("--sample-now", action="store_true", help="Execute the 4-hour background trend sampling immediately.")
    parser.add_argument("--force", action="store_true", help="Clear checkpoints and run 7 AM briefing from scratch.")
    parser.add_argument("--daemon", action="store_true", help="Start the 4-hour + daily 7:00 AM background scheduler.")

    args = parser.parse_args()

    if args.run_now:
        run_trend_radar_pipeline(force=args.force)
    elif args.sample_now:
        job_sample_and_update_trends()
    elif args.daemon:
        start_scheduler()
    else:
        print("Please specify an action:")
        print("  --run-now    : Run 7 AM daily email briefing immediately.")
        print("  --sample-now : Run 4-hour trend sampling immediately.")
        print("  --daemon     : Start the background scheduler (every 4h + 7 AM daily).")
        parser.print_help()
