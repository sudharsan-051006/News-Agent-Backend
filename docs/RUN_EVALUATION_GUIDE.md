# Elinity News-to-Fiction Engine: Evaluation & Benchmarking Operations Guide

This guide provides step-by-step instructions for engineers, QA testers, and reviewers to run the evaluation suite via CLI, API, and the Frontend Dashboard.

---

## 1. Running via Command Line Interface (CLI)

### 1.1 Triggering an Evaluation Run
To execute a full evaluation run against all active test cases in the database:

```bash
cd "D:\AI PYTHON PROJECTS\ai_news_trend_agent"
venv\Scripts\python.exe main.py --eval-run
```

**Terminal Output Example**:
```
=======================================================
EVALUATION RUN COMPLETE: RUN-B9E2F6E0
Status: COMPLETED | Total Evaluated: 4
Release Gate: 🛑 BLOCKED
Gate Block Reasons:
  - Metric precision_at_k: 0.75 < target 0.80
Execution Time: 115.42s | Estimated Cost: $0.0038
=======================================================
```

### 1.2 Starting the FastAPI Backend
To launch the backend API powering both the news trends and evaluation framework:

```bash
venv\Scripts\python.exe main.py --api --port 8000
```
API Documentation (Swagger UI) is available at: `http://localhost:8000/docs`

---

## 2. Running via REST API

### 2.1 Seed Pilot Dataset
Seeds the pilot multi-domain benchmark dataset into Neon PostgreSQL:

```http
POST /api/fiction/evaluation/datasets/{dataset_id}/seed-pilot
```

### 2.2 Trigger an Evaluation Run
Initiate an asynchronous evaluation run:

```http
POST /api/fiction/evaluation/run
Content-Type: application/json

{
  "dataset_id": 1,
  "run_name": "Weekly QA Release Check",
  "model_name": "llama-3.3-70b-instruct",
  "judge_model": "llama-3.3-70b-instruct"
}
```

**Response**:
```json
{
  "run_id": "RUN-A1C8E4F9",
  "status": "RUNNING",
  "message": "Evaluation run initiated successfully."
}
```

### 2.3 Check Run Status & Acceptance Scorecard
```http
GET /api/fiction/evaluation/runs/RUN-A1C8E4F9
```

**Response**:
```json
{
  "run_id": "RUN-A1C8E4F9",
  "status": "COMPLETED",
  "release_ready": false,
  "gate_block_reasons": ["Metric precision_at_k: 0.75 < target 0.80"],
  "total_cases": 4,
  "total_duration_seconds": 115.42,
  "total_cost_usd": 0.0038
}
```

### 2.4 Retrieve Stored Artifacts (JSON, Markdown, CSV)
```http
GET /api/fiction/evaluation/runs/RUN-A1C8E4F9/reports
```

### 2.5 Run Baseline Benchmarking Suite
Compares Baselines A, B, C, and D across the test cases:

```http
POST /api/fiction/evaluation/benchmark
Content-Type: application/json

{
  "dataset_id": 1,
  "baselines": ["BASELINE_A", "BASELINE_B", "BASELINE_C", "BASELINE_D"]
}
```

### 2.6 Run Architectural Ablation Study
Evaluates the delta impact of removing specific components:

```http
POST /api/fiction/evaluation/ablation
Content-Type: application/json

{
  "dataset_id": 1,
  "ablation_names": [
    "no_event_extraction",
    "no_relationship_discovery",
    "no_scenario_evaluation",
    "no_continuity_tracking"
  ]
}
```

---

## 3. Using the Frontend Evaluation Dashboard

1. Start the React Frontend:
   ```bash
   cd "D:\AI PYTHON PROJECTS\news_web"
   npm run dev
   ```
2. Navigate to: `http://localhost:5173/fiction/evaluation`
3. The dashboard provides 6 interactive tabs:
   * **Acceptance Target Scorecard**: Overview of all release gates, current scores, targets, and pass/blocked indicators.
   * **Component Metrics Deep Dive**: Drill down into Event Extraction, Entity Resolution, Relationships, Clustering, Scenarios, Story Quality, and Latency.
   * **Baseline Benchmark Comparison**: Side-by-side bar charts comparing Baselines A–D on Story Quality, Flesch Readability, and Precision@K.
   * **Ablation Analysis**: Visualizes degradation deltas when components are disabled.
   * **Human Review & Annotation Form**: Interface for human raters to submit 1–5 rubric scores and calculate Cohen's Kappa.
   * **Executive Reports**: View and download Markdown, JSON, and CSV reports generated from evaluation runs.

---

## 4. Running Automated Tests

To run the complete automated test suite (mocking LLM calls):

```bash
cd "D:\AI PYTHON PROJECTS\ai_news_trend_agent"
venv\Scripts\python.exe -m unittest discover tests
```

Expected result:
```
Ran 23 tests in 1.48s
OK
```
