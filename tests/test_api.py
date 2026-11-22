"""
API Endpoint Integration Tests for Elinity Platform & Fiction Engine.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from api import app


class TestElinityAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "ok")

    def test_trends_endpoint(self):
        response = self.client.get("/api/trends?limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("trends", data)
        self.assertIn("count", data)

    def test_fiction_events_endpoint(self):
        response = self.client.get("/api/fiction/events?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("events", data)

    def test_fiction_clusters_endpoint(self):
        response = self.client.get("/api/fiction/clusters?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("clusters", data)

    def test_fiction_stories_endpoint(self):
        response = self.client.get("/api/fiction/stories?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("stories", data)


if __name__ == "__main__":
    unittest.main()
