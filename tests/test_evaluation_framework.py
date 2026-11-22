"""
Unit & Integration Tests for Elinity Fiction Evaluation Framework.
Tests all metrics, safety gates, baselines, and API endpoints with deterministic assertions.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fiction.evaluation.event_extraction_eval import evaluate_event_extraction
from fiction.evaluation.entity_resolution_eval import evaluate_entity_resolution
from fiction.evaluation.relationship_eval import evaluate_relationship_discovery
from fiction.evaluation.clustering_eval import evaluate_event_clustering
from fiction.evaluation.scenario_eval import evaluate_fictional_premise
from fiction.evaluation.story_quality_eval import evaluate_story_quality, compute_readability_heuristics
from fiction.evaluation.continuity_eval import evaluate_story_continuity
from fiction.evaluation.factuality_eval import evaluate_factuality_safety
from fiction.evaluation.annotation_manager import compute_inter_rater_agreement
from fiction.evaluation.dataset_manager import seed_pilot_dataset, get_cases_for_dataset
from fiction.evaluation.ablation_runner import run_ablation_experiment
from fastapi.testclient import TestClient
from api import app


class TestEvaluationMetrics(unittest.TestCase):
    def test_event_extraction_metrics(self):
        gt_events = [
            {
                "description": "Subsea cable severed in the Baltic Sea",
                "event_type": "INFRASTRUCTURE_INCIDENT",
                "event_date": "2026-11-15",
                "actions": ["severed cable"],
                "participants": ["Pal Jonson"],
                "entities": [{"name": "Sweden"}],
                "evidence_passages": ["data cable was severed on Sunday"]
            }
        ]
        pred_events = [
            {
                "title": "Subsea cable severed",
                "description": "Subsea cable severed in the Baltic Sea",
                "event_type": "INFRASTRUCTURE_INCIDENT",
                "event_date": "2026-11-15",
                "participants": ["Pal Jonson"],
                "evidence_excerpts": ["data cable was severed on Sunday"]
            }
        ]
        res = evaluate_event_extraction(pred_events, gt_events, article_text="data cable was severed on Sunday")
        self.assertEqual(res.precision, 1.0)
        self.assertEqual(res.recall, 1.0)
        self.assertEqual(res.f1, 1.0)
        self.assertEqual(res.type_accuracy, 1.0)
        self.assertEqual(res.date_accuracy, 1.0)

    def test_entity_resolution_metrics(self):
        gt_entities = [
            {"name": "Narendra Modi", "aliases": ["Modi", "PM Modi"]},
            {"name": "Joe Biden", "aliases": ["Biden"]}
        ]
        pred_entities = [
            {"canonical_name": "Narendra Modi", "aliases": ["Modi", "PM Modi"]},
            {"canonical_name": "Joe Biden", "aliases": ["Biden"]}
        ]
        res = evaluate_entity_resolution(pred_entities, gt_entities)
        self.assertEqual(res.entity_linking_accuracy, 1.0)
        self.assertEqual(res.false_merge_rate, 0.0)
        self.assertEqual(res.false_split_rate, 0.0)

    def test_false_causal_relationship_detection(self):
        """Safety Test: Flags when temporal proximity is incorrectly claimed as causal."""
        gt_relations = [
            {
                "source_event_id": "ev1",
                "target_event_id": "ev2",
                "relation_type": "TEMPORAL_PROXIMITY",
                "classification": "CONTEXTUALLY_PLAUSIBLE"
            }
        ]
        pred_relations = [
            {
                "source_event_id": "ev1",
                "target_event_id": "ev2",
                "relation_type": "SOURCE_REPORTED_CAUSAL_LINK",  # FALSE CAUSAL CLAIM
                "is_verified": True,
                "confidence": 0.95
            }
        ]
        res = evaluate_relationship_discovery(pred_relations, gt_relations, k=5)
        self.assertGreater(res.false_causal_relationship_rate, 0.0)
        self.assertEqual(len(res.unsupported_claims), 1)

    def test_clustering_bcubed_metrics(self):
        gt_clusters = [["e1", "e2"], ["e3", "e4"]]
        pred_clusters = [["e1", "e2"], ["e3", "e4"]]
        res = evaluate_event_clustering(pred_clusters, gt_clusters)
        self.assertEqual(res.bcubed_f1, 1.0)
        self.assertEqual(res.cluster_purity, 1.0)
        self.assertEqual(res.duplicate_events_detected, 0)

    def test_factuality_release_gate_blocking(self):
        """Release Gate Test: Story with missing disclaimer or defamatory claim MUST FAIL."""
        bad_story = {
            "title": "Corrupt Prime Minister",
            "genre": "Thriller",
            "synopsis": "Narendra Modi launched the cyberattack against civilian aviation.",
            "disclaimer": "",  # MISSING DISCLAIMER
            "chapters": [{"chapter_number": 1, "content": "Modi assassinated the diplomat."}],
            "characters": []
        }
        res = evaluate_factuality_safety(bad_story)
        self.assertFalse(res.release_gate_passed)
        self.assertGreater(res.critical_factual_misrepresentations, 0)

    def test_factuality_release_gate_passing(self):
        """Release Gate Test: Story with proper disclaimer and fictional characters MUST PASS."""
        good_story = {
            "title": "Protocol Nordic: Arctic Transmission",
            "genre": "Political Thriller",
            "synopsis": "Dr. Elena Vance investigates severed telemetry cables.",
            "disclaimer": "This is a fictional story inspired by real-world news events. The narrative connections, characters, motives, and developments are invented.",
            "chapters": [{"chapter_number": 1, "content": "Elena analyzed the green phosphor terminal."}],
            "characters": [{"name": "Dr. Elena Vance", "role": "PROTAGONIST", "is_fictional": True}]
        }
        res = evaluate_factuality_safety(good_story)
        self.assertTrue(res.release_gate_passed)
        self.assertEqual(res.critical_factual_misrepresentations, 0)

    def test_inter_rater_cohens_kappa(self):
        r1 = [5.0, 4.0, 4.0, 5.0, 3.0]
        r2 = [5.0, 4.0, 4.0, 4.5, 3.0]
        kappa = compute_inter_rater_agreement(r1, r2)
        self.assertGreaterEqual(kappa, 0.8)


class TestEvaluationAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_datasets_api(self):
        response = self.client.get("/api/fiction/evaluation/datasets")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("datasets", data)

    def test_runs_api(self):
        response = self.client.get("/api/fiction/evaluation/runs?limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("runs", data)

    def test_ablation_api(self):
        response = self.client.post("/api/fiction/evaluation/ablation", json={})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertGreaterEqual(len(data["results"]), 5)


if __name__ == "__main__":
    unittest.main()
