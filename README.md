# AI News Trend Radar Agent 📡⚡

An autonomous, multi-agent news intelligence and trend detection pipeline. It synchronizes RSS sources dynamically from **Supabase**, monitors news velocity across global and national domains, tracks a **6-day rolling topic baseline** in **Neon Serverless PostgreSQL**, detects **emergent trend velocity spikes**, verifies sources via autonomous internet search, and dispatches an executive intelligence email briefing **once a day at 07:00 AM IST**.

---

## 🚀 Key Capabilities & Architectural Highlights

### 1. Dynamic Ingestion Synced from Supabase
- **Zero Static Feeds**: Synchronizes active RSS sources directly from Supabase project table `rss` into Neon DB (`feeds` table).
- **Publisher Fairness**: Collects up to 10 balanced recent articles per active publisher, eliminating source dominance while capturing breaking events.
- **Full In-Article Text & Image Extraction**: Scrapes body content and high-resolution OpenGraph / article images using `trafilatura` and `BeautifulSoup`.

### 2. Autonomous Event Clustering & Natural Domain Detection
- **Dynamic Event Discovery**: Replaces rigid hardcoded tags with zero-shot semantic event clustering (e.g., `NZ vs IND 5th ODI Decider`, `Ukraine Oil Refinery Drone Blitz`, `Anthropic Claude Code Parallel Workers`).
- **Natural Pillar Classification**: The AI autonomously assigns macro domains based strictly on story content:
  - ⚡ `Technology & AI`
  - 🌐 `Geopolitics & Security`
  - 🇮🇳 `India Affairs`
  - 📈 `Finance & Markets`
  - 🏆 `Sports`
  - 🎬 `Entertainment & Movies`
  - 🌿 `Science & Environment`
- **Intra-Day Deduplication**: Merges multi-outlet coverage for the same story across 4-hour ingestion runs, consolidating reference links and updating velocity scores instead of creating duplicate cards.
- **Strict Reference & Image Integrity**: Every topic snapshot is strictly validated. Topics without verified reference articles are automatically discarded; missing visuals are populated via **Wikimedia Commons API** and **Unsplash Render Search API**.

### 3. Dynamic 6-Day Rolling Trend Momentum
- Stores every discovered event in Neon PostgreSQL with timestamped snapshot data.
- Calculates trend velocity relative to its historical baseline:
  $$V(t) = \frac{\text{Today's Volume}}{\mu_{\text{6-Day Baseline}} + 0.5}$$
- Distinguishes between `BREAKING`, `EMERGING`, and `STEADY` momentum.

### 4. CrewAI Editorial Verification & Critic Gatekeeper
```
[Supabase RSS Feeds] ➔ [News Scout] ➔ [Investigative Researcher] ➔ [Chief Editor] ➔ [Critic Gatekeeper] ➔ [Executive Email]
                             │                       │                      │                    │
                      Computes 6-Day            ReAct Search         Synthesizes        Audits Quality &
                      Trend Velocity          (Verifies Facts)     "Why It Matters"     Decides Go / No-Go
```
- **Investigative Researcher**: Performs autonomous search verification via DuckDuckGo for primary source validation.
- **Chief Editor**: Synthesizes verified evidence into crisp 2-sentence summaries and bold "Why It Matters" impact assessments.
- **Critic Gatekeeper**: Audits the briefing against an editorial quality threshold (Score $\ge 8.5/10$). Suppresses email dispatch if news signals are flat to prevent inbox clutter.

### 5. Resilient Database Layer
- **Auto-Reconnect with `@db_retry`**: Automatically recovers from Neon serverless pooler sleep cycles and connection drops.
- **TCP Keepalives**: Enforces active keepalives to maintain long-lived polling connections.

---

## 🛠️ Tech Stack

| Layer | Technology | Role |
| :--- | :--- | :--- |
| **Agent Framework** | **CrewAI** | Multi-agent coordination with cognitive roles |
| **LLM Inference** | **Local Ollama (Mistral)** / **Groq (Llama-3.3)** / **OpenRouter** | 100% offline local running with zero rate limits, or cloud fallback |
| **Database** | **Neon DB (Serverless PostgreSQL)** | 6-day rolling topic snapshots, articles, and audit logs |
| **Feed Catalog** | **Supabase (`rss` table)** | Remote user/admin RSS source configuration |
| **Autonomous Search** | **Wikimedia API + Render Unsplash + DuckDuckGo** | Real photo finding & breaking news verification |
| **Frontend Dashboard** | **Vite + React (`news_web`)** | Responsive web radar with horizontal scrolling category navigation |
| **Scheduler & CI/CD**| **APScheduler + GitHub Actions** | 4-Hour background sampling & 7:00 AM IST email briefing |

---

## 📂 Repository Structure

```
├── .github/workflows/
│   ├── trend_sampling.yml     # Automated 4-hour background sampling & DB update
│   └── daily_briefing.yml     # Automated 7:00 AM IST email briefing
├── agents/
│   └── crew.py                # CrewAI agent definitions, tasks, and critic gatekeeper
├── tools/
│   ├── image_finder.py        # Wikimedia Commons & Unsplash Render image finder
│   ├── rss_tools.py           # Feed polling, body extraction & article ingestion
│   ├── search_tools.py        # DuckDuckGo ReAct search tool
│   └── trend_calculator.py    # Dynamic clustering, velocity math, and alignment checks
├── config.py                  # Pydantic environment configuration
├── database.py                # Neon DB operations, Supabase sync, and @db_retry logic
├── email_service.py           # Jinja2 HTML responsive email formatter & SMTP sender
├── feeds.json                 # Local fallback RSS catalog
├── llm_adapter.py             # Unified client for Ollama, Groq, and OpenRouter
├── main.py                    # CLI entrypoint, dual scheduler, and pipeline orchestrator
├── requirements.txt           # Python dependencies
└── .env.example               # Configuration template
```

---

## 🚀 Getting Started

### 1. Environment Setup
```bash
# Clone the repository
git clone -b Trend https://github.com/sudharsan-051006/News-Agent-Backend.git
cd News-Agent-Backend

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate   # On Windows
# source venv/bin/activate # On Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```
Key configuration items:
- `DATABASE_URL`: Neon PostgreSQL connection string (`?sslmode=require`)
- `LLM_PROVIDER`: `ollama` (for local Mistral), `groq`, or `openrouter`
- `SUPABASE_URL` & `SUPABASE_KEY`: Supabase project URL and service role key
- `EMAIL_USER` & `EMAIL_PASSWORD`: Gmail SMTP credentials
- `EMAIL_RECIPIENT`: Destination email address (`sudharsan05106@gmail.com`)

### 3. Execution Commands

#### Run 4-Hour Trend Momentum Sampling (Database Only, No Email)
```bash
python main.py --sample-now
```

#### Run Immediate Full Pipeline & Send Briefing Email
```bash
python main.py --run-now --force
```

#### Start Continuous Background Daemon
```bash
python main.py --daemon
```
Runs trend sampling every 4 hours and automatically delivers the briefing email daily at 07:00 AM IST.

---

## ⏰ Automated GitHub Actions Workflows

This branch includes two production GitHub Actions workflows:
1. **[4-Hour Trend Momentum Sampling](.github/workflows/trend_sampling.yml)**: Runs at `00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC` to refresh topic snapshots in Neon DB.
2. **[Daily 7:00 AM Trend Briefing](.github/workflows/daily_briefing.yml)**: Runs at `01:30 UTC` (07:00 AM IST) to evaluate significance and send the daily executive email.
