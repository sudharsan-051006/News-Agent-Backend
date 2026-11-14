"""
Configuration manager for AI News Trend Radar Agent.
Loads settings from .env with Pydantic validation.
"""

import os
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # Database (Neon PostgreSQL)
    DATABASE_URL: str = Field(
        default="postgresql://user:password@localhost:5432/neondb",
        description="Neon DB PostgreSQL connection string with sslmode=require"
    )

    # LLM Settings (OpenRouter, Groq, or Local Ollama)
    LLM_PROVIDER: Literal["openrouter", "groq", "ollama"] = "openrouter"
    
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"
    
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Local Ollama Settings (100% Offline / Zero API Keys)
    OLLAMA_MODEL: str = "mistral"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Email Settings (SMTP)
    EMAIL_HOST: str = "smtp.gmail.com"
    EMAIL_PORT: int = 587
    EMAIL_USER: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_RECIPIENT: str = ""

    # Agentic Thresholds & Autonomy
    MIN_TREND_VELOCITY_SCORE: float = 3.0
    CRITIC_APPROVAL_THRESHOLD: float = 8.5
    ENABLE_SIGNIFICANCE_GATE: bool = True

    # Scheduler Settings
    DAILY_RUN_HOUR: int = 7          # Send email briefing every day at 07:00 AM
    DAILY_RUN_MINUTE: int = 0
    SAMPLING_INTERVAL_HOURS: int = 4 # Run trend sampling & DB ingestion every 4 hours

    # Supabase RSS Sync Settings
    SUPABASE_URL: str = "https://atonkzxonfemlctmtdvo.supabase.co"
    SUPABASE_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
