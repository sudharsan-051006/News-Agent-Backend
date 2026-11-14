"""
Unified LLM Adapter for OpenRouter and Groq.
Provides automatic fallback and unified interfaces for CrewAI and raw completions.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from openai import OpenAI
from crewai import LLM
from config import settings

logger = logging.getLogger("agent.llm")


def get_crewai_llm() -> LLM:
    """
    Returns a CrewAI-compatible LLM instance based on LLM_PROVIDER.
    Supports OpenRouter, Groq, and local Ollama with seamless toggle.
    """
    provider = settings.LLM_PROVIDER.lower()

    if provider == "ollama":
        model_name = settings.OLLAMA_MODEL
        if not model_name.startswith("ollama/"):
            model_name = f"ollama/{model_name}"
        logger.info(f"Using Local Ollama LLM: {model_name} at {settings.OLLAMA_BASE_URL}")
        return LLM(
            model=model_name,
            base_url=settings.OLLAMA_BASE_URL
        )
    elif provider == "groq":
        model_name = settings.GROQ_MODEL
        if not model_name.startswith("groq/"):
            model_name = f"groq/{model_name}"
        logger.info(f"Using Groq LLM: {model_name}")
        return LLM(
            model=model_name,
            api_key=settings.GROQ_API_KEY
        )
    else:
        model_name = settings.OPENROUTER_MODEL
        if not model_name.startswith("openrouter/"):
            model_name = f"openrouter/{model_name}"
        logger.info(f"Using OpenRouter LLM: {model_name}")
        return LLM(
            model=model_name,
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1"
        )


class ResilientLLMClient:
    """
    Standard OpenAI-compatible client wrapper that attempts the primary provider
    and automatically falls back on rate-limits/errors.
    """

    def __init__(self):
        self.primary_provider = settings.LLM_PROVIDER.lower()

    def get_client_and_model(self, provider: str):
        if provider == "ollama":
            return OpenAI(
                base_url=f"{settings.OLLAMA_BASE_URL}/v1",
                api_key="ollama"
            ), settings.OLLAMA_MODEL
        elif provider == "groq":
            return OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=settings.GROQ_API_KEY
            ), settings.GROQ_MODEL
        else:
            return OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.OPENROUTER_API_KEY,
                default_headers={
                    "HTTP-Referer": "https://github.com/ai-trend-radar-agent",
                    "X-Title": "AI Trend Radar Agent"
                }
            ), settings.OPENROUTER_MODEL

    def generate(self, messages: List[Dict[str, str]], temperature: float = 0.3, max_tokens: int = 1500) -> str:
        """Executes completion with automatic fallback."""
        primary = self.primary_provider
        secondary = "groq" if primary == "openrouter" else "openrouter"

        for prov in [primary, secondary]:
            try:
                client, model = self.get_client_and_model(prov)
                if not client.api_key:
                    logger.warning(f"No API key provided for {prov}, skipping.")
                    continue

                logger.info(f"Dispatching prompt to {prov} ({model})...")
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.error(f"Error calling {prov}: {e}. Attempting fallback...")
                continue

        raise RuntimeError("Both primary and secondary LLM providers failed to complete the request.")


llm_client = ResilientLLMClient()
