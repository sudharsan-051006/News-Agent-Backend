# Elinity News-to-Fiction Engine: Evaluation, Benchmarking & QA Framework

## 1. Executive Overview

The **Elinity News-to-Fiction Engine** converts real-world news articles into interconnected, creative fictional narratives across multi-chapter stories while enforcing a strict boundary between facts and fiction.

The Evaluation, Benchmarking, and Quality Assurance Framework provides:
1. Ground-truth evaluation dataset management and standardized test cases.
2. Component-level quantitative metrics for every stage in the extraction, clustering, and narrative generation pipeline.
3. Automated release gating with hard stop criteria for factuality, defamation protection, and narrative continuity.
4. Standardized baseline benchmarks (A, B, C, D) and ablation experiment harnesses.
5. Latency profiling, token usage accounting, and USD cost tracking.
6. Multi-rater human review aggregation with Cohen's weighted Kappa.
7. Complete REST API endpoints and an interactive React frontend evaluation dashboard.

---

## 2. Architecture & Pipeline Stages

```
   ┌────────────────────────────────────────────────────────┐
   │                  Raw News Ingestion                    │
   └──────────────────────────┬─────────────────────────────┘
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │            Stage 1: News Event Extraction              │
   │  Precision, Recall, F1, Type/Date/Entity/Evidence Acc │
   └──────────────────────────┬─────────────────────────────┘
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │            Stage 2: Entity Resolution                  │
   │  Resolution Acc, False Merge Rate, False Split Rate    │
   └──────────────────────────┬─────────────────────────────┘
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │       Stage 3: Cross-Event Relationship Discovery      │
   │  Precision@K, Evidence Support Rate, Causal Accuracy   │
   └──────────────────────────┬─────────────────────────────┘
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │            Stage 4: Event Graph & Clustering           │
   │  B-cubed P/R/F1, Cluster Purity, Completeness          │
   └──────────────────────────┬─────────────────────────────┘
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │     Stage 5: Premise Generation & Scenario Eval        │
   │  8-criteria 1-5 rubric (Plausibility, Originality, etc)│
   └──────────────────────────┬─────────────────────────────┘
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │     Stage 6: Story Architecture & Chapter Writer       │
   │  10-criteria 1-5 rubric, Flesch Reading Ease           │
   └──────────────────────────┬─────────────────────────────┘
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │        Stage 7: Continuity & Release Gate Auditor      │
   │  Zero Defamation Tolerance, Fiction Disclaimers        │
   └──────────────────────────┬─────────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
       [RELEASE: PASSED]             [RELEASE: BLOCKED]
```

---

## 3. Component Metrics & Mathematical Formulations

### 3.1 Event Extraction Metrics
* **Token Jaccard Match**: Matches predicted events to ground-truth events:
  $$J(E_p, E_{gt}) = \frac{|Tokens(E_p) \cap Tokens(E_{gt})|}{|Tokens(E_p) \cup Tokens(E_{gt})|}$$
  A bipartite match is established when $J \ge 0.40$.
* **Precision**: $\frac{TP}{TP + FP}$
* **Recall**: $\frac{TP}{TP + FN}$
* **F1 Score**: $2 \times \frac{P \times R}{P + R}$
* **Attribute Accuracies**: Exact and semantic match rates for `event_type`, `date`, `entities`, and `verbatim_source`.

### 3.2 Entity Resolution Metrics
* **Resolution Accuracy**: Fraction of entity mentions mapped to the correct canonical entity.
* **False Merge Rate**: Rate of grouping distinct entities under the same canonical name.
* **False Split Rate**: Rate of splitting aliases of the same entity into separate canonical records.

### 3.3 Cross-Event Relationship Discovery Metrics
* **Precision@K**: Fraction of top-K predicted relationships that exist in ground truth:
  $$\text{Precision@K} = \frac{|\text{Top-K Predictions} \cap \text{Ground Truth}|}{K}$$
* **Evidence Support Rate**: Fraction of discovered relationships supported by source text citations.
* **False Causal Rate**: Rate of inferring causal relationships without explicit textual justification.

### 3.4 Clustering Metrics (B-cubed & Purity)
* **B-cubed Precision**:
  $$\text{BCubed-P} = \frac{1}{N} \sum_{i=1}^N \frac{|C(i) \cap L(i)|}{|C(i)|}$$
* **B-cubed Recall**:
  $$\text{BCubed-R} = \frac{1}{N} \sum_{i=1}^N \frac{|C(i) \cap L(i)|}{|L(i)|}$$
* **Cluster Purity**: Fraction of elements belonging to the majority class in each cluster.

### 3.5 Narrative Quality & Readability
* **Story Quality Score**: 10-criteria evaluation on a 1–5 scale (Plot Coherence, Pacing, Character Voice, Tension, Dialogue, Thematic Resonance, Emotional Engagement, World Consistency, Structure, Polish).
* **Flesch Reading Ease Formula**:
  $$206.835 - 1.015 \left(\frac{\text{total words}}{\text{total sentences}}\right) - 84.6 \left(\frac{\text{total syllables}}{\text{total words}}\right)$$
  Target range: 60.0–85.0.

### 3.6 Inter-Rater Reliability (Cohen's Weighted Kappa)
$$\kappa_w = 1 - \frac{\sum_{i,j} w_{ij} O_{ij}}{\sum_{i,j} w_{ij} E_{ij}}$$
Measures agreement between human reviewers with quadratic penalization for severe rating disagreements.

---

## 4. Hard Release Gating Criteria

A story generation pipeline execution is strictly **BLOCKED** if any of the following production criteria fail:

| Acceptance Criterion | Minimum Target | Gating Impact |
| :--- | :--- | :--- |
| **Event Extraction F1** | $\ge 0.85$ | BLOCKED |
| **Entity Resolution Accuracy** | $\ge 0.90$ | BLOCKED |
| **Relationship Precision@K** | $\ge 0.80$ | BLOCKED |
| **B-cubed Clustering F1** | $\ge 0.75$ | BLOCKED |
| **Story Quality Rating** | $\ge 4.0 / 5.0$ | BLOCKED |
| **Factuality & Disclaimer Guard** | $\ge 4.5 / 5.0$ | BLOCKED |
| **Continuity Consistency Rate** | $\ge 0.90$ | BLOCKED |
| **Defamation / Critical Misrepresentations** | **STRICTLY 0** | **IMMEDIATE HARD BLOCK** |

### Zero Defamation Tolerance
The engine strictly audits every generated story:
* Real living figures (e.g. Narendra Modi, Joe Biden, etc.) MUST NEVER be portrayed committing fictional crimes, violence, corruption, or defamatory acts.
* Fictional negative actions must always be attributed to fictional characters.
* Every story must include a clear, prominent fiction disclaimer stating that real-world events have been creatively reimagined into a fictional scenario.

---

## 5. Benchmarking Baselines & Ablation Studies

### Baselines
* **Baseline A (Direct Prompting)**: Zero-shot prompt fed raw articles directly into LLM without intermediate extraction or graph construction.
* **Baseline B (Pipeline Without Relationship Discovery)**: Uses event extraction and clustering, but skips cross-event link discovery.
* **Baseline C (Pipeline Without Scenario Evaluation)**: Generates story outlines directly from clusters without candidate scenario evaluation.
* **Baseline D (Full Pipeline)**: The complete 12-stage Elinity News-to-Fiction Engine.

### Ablation Variants
* `no_event_extraction`: Feeds raw article text directly into clustering.
* `no_entity_resolution`: Retains raw surface mentions without canonical entity mapping.
* `no_relationship_discovery`: Clusters events solely on lexical similarity.
* `no_evidence_verification`: Omits verification of relational claims.
* `no_scenario_evaluation`: Selects the first generated premise without multi-criteria scoring.
* `no_continuity_tracking`: Writes chapters independently without memory state.
* `no_safety_filter`: Simulates story generation with safety gating disabled (audit benchmark only).

---

## 6. Database Schema Summary (PostgreSQL)

The evaluation suite operates on 8 dedicated tables in Neon PostgreSQL:
1. `fiction_eval_datasets`: Ground truth datasets.
2. `fiction_eval_cases`: Test cases with source news articles.
3. `fiction_eval_annotations`: Ground-truth events, entities, and relationships.
4. `fiction_eval_runs`: Executed evaluation and benchmark runs.
5. `fiction_eval_metrics`: Fine-grained component metrics per case and per run.
6. `fiction_eval_reviews`: Human reviewer scores and qualitative feedback.
7. `fiction_eval_comparisons`: Baseline and ablation comparative analysis results.
8. `fiction_eval_artifacts`: Stored Markdown, JSON, and CSV executive reports.
