"""
Unit Tests for Elinity Fiction Engine Core AI & Graph Modules.
All tests use deterministic assertions and mocked LLMs where appropriate.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
from fiction.entity_resolver import normalize_entity_name, resolve_entity
from fiction.relation_verifier import verify_event_relationship
from fiction.event_graph import EventGraph, build_graph_from_db
from fiction.schemas import ExtractedEvent, FictionalScenarioModel, ScenarioEvaluationScores


class TestEntityResolver(unittest.TestCase):
    def test_alias_normalization(self):
        canonical, ent_type, _ = resolve_entity("n. modi")
        self.assertEqual(canonical, "Narendra Modi")
        canonical, ent_type, _ = resolve_entity("Prime Minister Narendra Modi")
        self.assertEqual(canonical, "Narendra Modi")
        canonical, ent_type, _ = resolve_entity("Google LLC")
        self.assertEqual(canonical, "Google")
        canonical, ent_type, _ = resolve_entity("The White House")
        self.assertEqual(canonical, "White House")

    def test_entity_classification(self):
        canonical, ent_type, _ = resolve_entity("Narendra Modi", "PERSON")
        self.assertEqual(canonical, "Narendra Modi")
        self.assertEqual(ent_type, "PERSON")

        canonical, ent_type, _ = resolve_entity("OpenAI", "ORG")
        self.assertEqual(canonical, "OpenAI")
        self.assertEqual(ent_type, "ORG")


class TestRelationVerifier(unittest.TestCase):
    def test_temporal_proximity_is_not_causal(self):
        """Strict Rule: Temporal proximity is NEVER classified as causal without proof."""
        ev_a = {"title": "Summit Concludes", "event_type": "DIPLOMACY"}
        ev_b = {"title": "Flight Outage", "event_type": "INFRASTRUCTURE"}

        rel_type, is_verified, conf, evidence = verify_event_relationship(
            ev_a, ev_b, heuristic_relation="TEMPORAL_PROXIMITY", shared_context="Events within 2 days"
        )
        self.assertEqual(rel_type, "TEMPORAL_PROXIMITY")
        self.assertFalse(is_verified)
        self.assertIn("No causal link established", evidence)

    def test_shared_entity_is_verified(self):
        ev_a = {"title": "Tech Keynote", "event_type": "ANNOUNCEMENT"}
        ev_b = {"title": "Antitrust Hearing", "event_type": "REGULATORY"}

        rel_type, is_verified, conf, evidence = verify_event_relationship(
            ev_a, ev_b, heuristic_relation="SHARED_ENTITY", shared_context="Google"
        )
        self.assertEqual(rel_type, "SHARED_ENTITY")
        self.assertTrue(is_verified)


class TestEventGraph(unittest.TestCase):
    def setUp(self):
        self.graph = EventGraph()
        self.graph.add_event(1, {"title": "Event 1"})
        self.graph.add_event(2, {"title": "Event 2"})
        self.graph.add_event(3, {"title": "Event 3"})
        self.graph.add_entity(101, "Dr. Alice")

        # Event 1 <-> Entity 101 <-> Event 2
        self.graph.add_event_entity_edge(1, 101)
        self.graph.add_event_entity_edge(2, 101)

        # Event 2 <-> Event 3 direct relation
        self.graph.add_event_relation_edge(2, 3, "TEMPORAL_PROXIMITY")

    def test_multi_hop_traversal(self):
        # Event 1 to Event 3 should be reachable in 3 hops (Event 1 -> Entity 101 -> Event 2 -> Event 3)
        path = self.graph.find_shortest_path(1, 3)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], "event:1")
        self.assertEqual(path[-1], "event:3")

    def test_candidate_cluster_extraction(self):
        clusters = self.graph.extract_candidate_clusters(min_events=3, max_events=6)
        self.assertEqual(len(clusters), 1)
        self.assertIn(1, clusters[0])
        self.assertIn(2, clusters[0])
        self.assertIn(3, clusters[0])


class TestSchemas(unittest.TestCase):
    def test_mandatory_disclaimer(self):
        scenario = FictionalScenarioModel(
            title="The Arctic Protocol",
            genre="Political Thriller",
            logline="A data leak shakes northern diplomacy.",
            premise="When a communications cable is severed...",
            central_conflict="Elena vs rogue sub-contractor",
            narrative_stakes="Arctic treaty breakdown"
        )
        self.assertIn("This is a fictional story inspired by real-world news events", scenario.disclaimer)

    def test_evaluation_bounds(self):
        scores = ScenarioEvaluationScores(
            event_coverage=8.0,
            narrative_coherence=8.5,
            originality=7.5,
            genre_suitability=9.0,
            diversity=8.0,
            source_traceability=9.0,
            fact_fiction_separation=10.0,
            total_score=8.57,
            is_approved=True
        )
        self.assertTrue(scores.is_approved)
        self.assertGreaterEqual(scores.total_score, 7.0)


if __name__ == "__main__":
    unittest.main()
