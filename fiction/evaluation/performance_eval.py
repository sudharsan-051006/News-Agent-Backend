"""
Performance Evaluator for Elinity Fiction Evaluation Framework.
Tracks component latency, step durations, article processing speed,
and computes summary latency percentiles (Mean, Median, P95, Min, Max).
"""

import time
import statistics
import logging
from typing import Dict, Any, List

logger = logging.getLogger("fiction.evaluation.performance")


class PerformanceTimer:
    """Context manager and tracker for component latencies."""

    def __init__(self):
        self.step_durations: Dict[str, List[float]] = {}
        self.start_times: Dict[str, float] = {}

    def start_step(self, step_name: str):
        self.start_times[step_name] = time.perf_counter()

    def end_step(self, step_name: str) -> float:
        start = self.start_times.pop(step_name, None)
        if start is None:
            return 0.0
        duration = round(time.perf_counter() - start, 4)
        if step_name not in self.step_durations:
            self.step_durations[step_name] = []
        self.step_durations[step_name].append(duration)
        return duration

    def get_component_summary(self) -> Dict[str, float]:
        """Returns total time spent per component."""
        return {k: round(sum(v), 3) for k, v in self.step_durations.items()}

    def get_percentiles(self, step_name: str) -> Dict[str, float]:
        """Calculates Mean, Median, P95, Min, Max for a step."""
        samples = self.step_durations.get(step_name, [])
        if not samples:
            return {"mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}

        sorted_s = sorted(samples)
        p95_idx = max(0, int(len(sorted_s) * 0.95) - 1)

        return {
            "mean": round(statistics.mean(samples), 3),
            "median": round(statistics.median(samples), 3),
            "p95": round(sorted_s[p95_idx], 3),
            "min": round(min(samples), 3),
            "max": round(max(samples), 3),
            "sample_count": len(samples)
        }
