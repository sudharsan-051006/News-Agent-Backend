"""
Cost & Token Tracker for Elinity Fiction Evaluation Framework.
Tracks input tokens, output tokens, total tokens, and computes exact or estimated
API expenditure based on verified provider pricing schedules.
Rule: If pricing is unknown for a provider/model, mark cost as None and status as UNKNOWN.
"""

import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger("fiction.evaluation.cost_tracker")

# Verified pricing per 1 Million tokens (USD): (Input $/1M, Output $/1M)
MODEL_PRICING_PER_1M: Dict[str, Tuple[float, float]] = {
    # Groq Cloud
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "mixtral-8x7b-32768": (0.24, 0.24),

    # Google Gemini
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),

    # Local / Free Tier
    "ollama": (0.0, 0.0),
    "llama3.2:3b": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "free": (0.0, 0.0),
}


class CostTracker:
    """Session tracker for token consumption and financial accounting."""

    def __init__(self, model_name: str = "llama-3.3-70b-versatile"):
        self.model_name = model_name
        self.input_tokens = 0
        self.output_tokens = 0
        self.retry_count = 0

    def record_usage(self, input_tokens: int, output_tokens: int, retries: int = 0):
        self.input_tokens += max(0, input_tokens)
        self.output_tokens += max(0, output_tokens)
        self.retry_count += max(0, retries)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def calculate_cost(self) -> Tuple[Optional[float], str]:
        """
        Calculates monetary cost in USD.
        Returns: (cost_usd, pricing_status: 'EXACT', 'ESTIMATED', or 'UNKNOWN')
        """
        key = self.model_name.lower()
        matched_pricing = None

        for k, pricing in MODEL_PRICING_PER_1M.items():
            if k in key:
                matched_pricing = pricing
                break

        if matched_pricing is not None:
            in_rate, out_rate = matched_pricing
            cost = (self.input_tokens * (in_rate / 1_000_000.0)) + (self.output_tokens * (out_rate / 1_000_000.0))
            status = "EXACT" if (in_rate > 0 or "ollama" in key) else "ESTIMATED"
            return round(cost, 6), status

        return None, "UNKNOWN"

    def get_summary(self) -> Dict[str, Any]:
        cost, status = self.calculate_cost()
        return {
            "model_name": self.model_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "retry_count": self.retry_count,
            "estimated_cost_usd": cost,
            "pricing_status": status
        }
