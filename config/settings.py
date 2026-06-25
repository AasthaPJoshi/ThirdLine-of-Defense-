"""
=============================================================================
ThirdLine — Central Settings Module
=============================================================================

FILE: config/settings.py

WHAT THIS FILE DOES:
    Single source of truth for all application configuration. Loads from
    environment variables (via config/.env), validates types and required
    fields, and exposes a typed `settings` singleton used throughout the
    codebase. Any misconfiguration fails loudly at startup rather than
    silently at runtime.

    Uses Pydantic Settings for validation — every field has a type, a
    default where safe, and a description. Adding a new config value means
    adding it here AND to config/.env.example.

HOW TO USE:
    from config.settings import settings

    # Access any config value
    project_id = settings.GCP_PROJECT_ID
    gemini_key = settings.GEMINI_API_KEY

DESIGN DECISIONS:
    - All secrets come from env vars — never hardcoded
    - LOCAL_MODE=true bypasses GCP calls for offline development
    - Nested settings classes keep related config grouped
    - Settings is a singleton (imported once, reused everywhere)

INPUT:  Environment variables (loaded from config/.env via python-dotenv)
OUTPUT: Typed `settings` object with validated configuration
=============================================================================
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root — all relative paths resolve from here
PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """
    Application-wide configuration, loaded from environment variables.

    Pydantic validates types on instantiation. Missing required fields
    raise a ValidationError with a clear message at startup.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / "config" / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # silently ignore unknown env vars
    )

    # ── [1] GCP Project ──────────────────────────────────────────────────────
    GCP_PROJECT_ID: str = Field(
        default="your-gcp-project-id",
        description="GCP project ID — set before running terraform apply",
    )
    GCP_REGION: str = Field(default="us-central1")
    GCP_ZONE: str = Field(default="us-central1-a")

    # ── [2] BigQuery ─────────────────────────────────────────────────────────
    BIGQUERY_DATASET: str = Field(default="thirdline")
    BIGQUERY_LOCATION: str = Field(default="US")

    # Fully-qualified table names (computed, not env vars)
    @property
    def bq_table_agent(self) -> str:
        return f"{self.GCP_PROJECT_ID}.{self.BIGQUERY_DATASET}.dim_agent"

    @property
    def bq_table_interaction(self) -> str:
        return f"{self.GCP_PROJECT_ID}.{self.BIGQUERY_DATASET}.fact_agent_interaction"

    @property
    def bq_table_evaluation(self) -> str:
        return f"{self.GCP_PROJECT_ID}.{self.BIGQUERY_DATASET}.fact_evaluation"

    @property
    def bq_table_finding(self) -> str:
        return f"{self.GCP_PROJECT_ID}.{self.BIGQUERY_DATASET}.fact_finding"

    @property
    def bq_table_control(self) -> str:
        return f"{self.GCP_PROJECT_ID}.{self.BIGQUERY_DATASET}.dim_control"

    @property
    def bq_table_ledger(self) -> str:
        return f"{self.GCP_PROJECT_ID}.{self.BIGQUERY_DATASET}.audit_ledger"

    @property
    def bq_table_review_queue(self) -> str:
        return f"{self.GCP_PROJECT_ID}.{self.BIGQUERY_DATASET}.human_review_queue"

    # ── [3] Cloud Storage ────────────────────────────────────────────────────
    GCS_BUCKET_RAW: str = Field(default="thirdline-raw-telemetry")
    GCS_BUCKET_ARTIFACTS: str = Field(default="thirdline-artifacts")

    # ── [4] Pub/Sub ──────────────────────────────────────────────────────────
    PUBSUB_TOPIC_TELEMETRY: str = Field(default="thirdline-agent-telemetry")
    PUBSUB_SUBSCRIPTION_TELEMETRY: str = Field(
        default="thirdline-agent-telemetry-sub"
    )

    # ── [5] Vertex AI ────────────────────────────────────────────────────────
    VERTEX_AI_LOCATION: str = Field(default="us-central1")
    VERTEX_AI_INDEX_ENDPOINT: str = Field(default="")
    VERTEX_AI_INDEX_ID: str = Field(default="")

    # ── [6] LLM APIs ─────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = Field(default="")
    GEMINI_MODEL: str = Field(default="gemini-1.5-flash")
    GEMINI_MODEL_JUDGE: str = Field(default="gemini-1.5-pro")

    ANTHROPIC_API_KEY: str = Field(default="")
    CLAUDE_MODEL: str = Field(default="claude-sonnet-4-6")

    # OpenAI (primary LLM judge)
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_JUDGE_MODEL: str = Field(default="gpt-4o-mini")

    # LangSmith (optional)
    LANGCHAIN_TRACING_V2: bool = Field(default=False)
    LANGCHAIN_API_KEY: str = Field(default="")
    LANGCHAIN_PROJECT: str = Field(default="thirdline")

    # ── [7] API / Security ───────────────────────────────────────────────────
    API_SECRET_KEY: str = Field(
        default="change-this-to-a-random-32-char-string",
        description="JWT signing key — change before any non-local deployment",
    )
    API_ALGORITHM: str = Field(default="HS256")
    API_TOKEN_EXPIRE_MINUTES: int = Field(default=480)

    # RBAC roles
    ROLE_AUDITOR: str = Field(default="auditor")
    ROLE_VALIDATOR: str = Field(default="validator")
    ROLE_AGENT_OWNER: str = Field(default="agent_owner")
    ROLE_LEADERSHIP: str = Field(default="leadership")

    # ── [8] Application ──────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    APP_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO"
    )
    APP_VERSION: str = Field(default="1.0.0")

    # ── [9] Local / Dev mode ─────────────────────────────────────────────────
    LOCAL_MODE: bool = Field(
        default=True,
        description="When True, skips GCP calls and uses local ChromaDB / file storage",
    )
    CHROMA_PERSIST_PATH: str = Field(default=".artifacts/chromadb")

    # ── [10] Synthetic data generation ───────────────────────────────────────
    SYNTHETIC_INTERACTIONS_PER_AGENT: int = Field(default=50)

    # Defect injection flags
    INJECT_HALLUCINATION: bool = Field(default=True)
    INJECT_BIAS: bool = Field(default=True)
    INJECT_DRIFT: bool = Field(default=True)
    INJECT_ROBUSTNESS: bool = Field(default=True)
    INJECT_RELIABILITY: bool = Field(default=True)

    # Drift simulation: interactions at or after this index show drift
    DRIFT_START_INDEX: int = Field(default=30)

    # ── [11] Evaluation thresholds ───────────────────────────────────────────
    HALLUCINATION_PASS_THRESHOLD: float = Field(default=0.75)
    BIAS_DISPARATE_IMPACT_THRESHOLD: float = Field(default=0.80)
    DRIFT_PSI_THRESHOLD: float = Field(default=0.20)
    RELIABILITY_PASS_THRESHOLD: float = Field(default=0.80)

    # ── [12] Audit ledger ────────────────────────────────────────────────────
    AUDIT_LEDGER_HASH_ALGORITHM: str = Field(default="sha256")

    # ── Validators ───────────────────────────────────────────────────────────
    @validator("API_SECRET_KEY")
    def secret_key_must_be_set_in_production(cls, v, values):
        """Warn loudly if the default secret key is used outside development."""
        if (
            values.get("APP_ENV") in ("staging", "production")
            and v == "change-this-to-a-random-32-char-string"
        ):
            raise ValueError(
                "API_SECRET_KEY must be changed from the default in staging/production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    @validator("GEMINI_API_KEY")
    def gemini_key_required_when_not_local(cls, v, values):
        """Warn if Gemini key is missing and we're not in local mode."""
        if not values.get("LOCAL_MODE", True) and not v:
            raise ValueError(
                "GEMINI_API_KEY is required when LOCAL_MODE=false. "
                "Get one at: https://aistudio.google.com"
            )
        return v

    # ── Derived paths ────────────────────────────────────────────────────────
    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    @property
    def logs_dir(self) -> Path:
        return PROJECT_ROOT / "logs"

    @property
    def artifacts_dir(self) -> Path:
        return PROJECT_ROOT / ".artifacts"

    @property
    def corpus_dir(self) -> Path:
        return PROJECT_ROOT / "governance" / "corpus"

    @property
    def rubrics_dir(self) -> Path:
        return PROJECT_ROOT / "evaluation" / "rubrics"


# ── Singleton ─────────────────────────────────────────────────────────────────
# Import this object everywhere — do not instantiate Settings() again elsewhere
settings = Settings()


# ── Quick smoke-test when run directly ───────────────────────────────────────
if __name__ == "__main__":
    import json

    print("\n=== ThirdLine Settings ===\n")
    safe = {
        "APP_ENV": settings.APP_ENV,
        "APP_VERSION": settings.APP_VERSION,
        "LOCAL_MODE": settings.LOCAL_MODE,
        "GCP_PROJECT_ID": settings.GCP_PROJECT_ID,
        "BIGQUERY_DATASET": settings.BIGQUERY_DATASET,
        "GEMINI_MODEL": settings.GEMINI_MODEL,
        "SYNTHETIC_INTERACTIONS_PER_AGENT": settings.SYNTHETIC_INTERACTIONS_PER_AGENT,
        "INJECT_HALLUCINATION": settings.INJECT_HALLUCINATION,
        "INJECT_BIAS": settings.INJECT_BIAS,
        "INJECT_DRIFT": settings.INJECT_DRIFT,
    }
    print(json.dumps(safe, indent=2))
    print(f"\nProject root: {settings.project_root}")
    print("Settings loaded successfully.\n")
