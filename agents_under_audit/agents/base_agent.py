"""
=============================================================================
ThirdLine — Base Synthetic Agent
=============================================================================

FILE: agents_under_audit/agents/base_agent.py

WHAT THIS FILE DOES:
    Abstract base class that every synthetic bank agent inherits from.
    Handles all the shared infrastructure:
      - OpenTelemetry GenAI span emission (the telemetry ThirdLine audits)
      - Pub/Sub publishing (sends telemetry to the ingest pipeline)
      - Interaction logging to local JSON (for LOCAL_MODE development)
      - Retry logic with exponential backoff for LLM calls
      - Token counting and latency measurement
      - Defect injection framework (subclasses define their own defects)
      - PII pre-scrubbing before any external call

    This is the telemetry heartbeat of the entire platform. Every
    interaction logged here becomes a row in fact_agent_interaction.

HOW IT WORKS:
    1. Subclass overrides `_build_system_prompt()` and `_should_inject_defect()`
    2. Client calls `respond(prompt, context, session_id, interaction_index)`
    3. Base class wraps the LLM call in an OTel span, measures latency,
       publishes to Pub/Sub (or writes locally), and returns the response
    4. If LOCAL_MODE, writes to data/interactions/{agent_id}/*.json

INHERITANCE:
    BaseAgent
    ├── MortgageFAQAgent       (defect: hallucination)
    ├── KYCSummaryAgent        (defect: reliability / PII leak)
    ├── LendingDecisionAgent   (defect: bias)
    ├── FXPostTradeAgent       (defect: drift)
    └── ComplianceQAAgent      (defect: robustness / prompt injection)

INPUT:
    prompt (str)              — user/caller query
    context (dict)            — optional context (e.g. retrieved docs, records)
    session_id (str)          — conversation session identifier
    interaction_index (int)   — ordinal index within this agent's run (for drift)
    proxy_attr (str)          — synthetic protected proxy attribute (bias testing)

OUTPUT:
    AgentResponse dataclass with:
      interaction_id, output, tool_calls, tokens, latency_ms,
      span_id, is_injected_defect, injected_defect_type
=============================================================================
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

# Internal imports
import sys
sys.path.insert(0, str(Path(__file__).parents[2]))
from config.settings import settings

logger = structlog.get_logger(__name__)


# ── Response dataclass ────────────────────────────────────────────────────────
@dataclass
class AgentResponse:
    """
    Structured response from any synthetic bank agent.

    Every field maps 1:1 to a column in fact_agent_interaction.
    This makes serialisation to BigQuery / JSON trivial.
    """
    interaction_id: str
    agent_id: str
    agent_name: str
    session_id: str
    interaction_index: int
    interaction_ts: str                          # ISO 8601
    prompt_redacted: str                         # input after PII scrub
    output_redacted: str                         # output after PII scrub
    output_raw: str                              # raw output (for local eval only)
    system_prompt_hash: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    retrieved_context: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = "stop"
    error_message: str = ""
    synthetic_proxy_attr: str = ""               # protected proxy attribute
    is_injected_defect: bool = False
    injected_defect_type: str = ""               # "hallucination" | "bias" | ...
    model_version_id: str = ""
    span_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to dict for BigQuery / JSON storage."""
        return {
            "interaction_id": self.interaction_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "session_id": self.session_id,
            "interaction_index": self.interaction_index,
            "interaction_ts": self.interaction_ts,
            "prompt_redacted": self.prompt_redacted,
            "output_redacted": self.output_redacted,
            "system_prompt_hash": self.system_prompt_hash,
            "tool_calls_json": json.dumps(self.tool_calls),
            "retrieved_context": self.retrieved_context,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "error_message": self.error_message,
            "synthetic_proxy_attr": self.synthetic_proxy_attr,
            "is_injected_defect": self.is_injected_defect,
            "injected_defect_type": self.injected_defect_type,
            "model_version_id": self.model_version_id,
            "span_id": self.span_id,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": settings.APP_VERSION,
        }


# ── Base agent ────────────────────────────────────────────────────────────────
class BaseAgent(ABC):
    """
    Abstract base class for all synthetic bank agents in ThirdLine's fleet.

    Subclasses must implement:
        agent_id:               unique identifier string
        agent_name:             human-readable name
        business_line:          e.g. "Consumer Lending"
        materiality_tier:       "HIGH" | "MEDIUM" | "LOW"
        _build_system_prompt(): returns the agent's system prompt
        _should_inject_defect():returns True if defect should fire
        _apply_defect():        modifies output to inject the defect
    """

    # ── Subclasses define these ───────────────────────────────────────────────
    agent_id: str = ""
    agent_name: str = ""
    business_line: str = ""
    materiality_tier: str = "HIGH"
    model_version_id: str = ""

    def __init__(self) -> None:
        self._system_prompt = self._build_system_prompt()
        self._system_prompt_hash = hashlib.sha256(
            self._system_prompt.encode()
        ).hexdigest()[:16]
        self._output_dir = (
            settings.data_dir / "interactions" / self.agent_id
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Initialise Gemini client
        self._llm = self._init_llm()

        logger.info(
            "agent_initialised",
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            tier=self.materiality_tier,
            local_mode=settings.LOCAL_MODE,
        )

    # ── Abstract methods ──────────────────────────────────────────────────────
    @abstractmethod
    def _build_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        ...

    @abstractmethod
    def _should_inject_defect(
        self, interaction_index: int, proxy_attr: str
    ) -> bool:
        """Return True if a defect should be injected in this interaction."""
        ...

    @abstractmethod
    def _apply_defect(self, prompt: str, output: str, interaction_index: int) -> str:
        """
        Modify the output to inject the defect.
        Called only when _should_inject_defect() returns True.
        Returns the modified output string.
        """
        ...

    @property
    @abstractmethod
    def defect_type(self) -> str:
        """Return the defect type string, e.g. 'hallucination'."""
        ...

    # ── LLM initialisation ────────────────────────────────────────────────────
    def _init_llm(self):
        """
        Initialise the LLM client. Uses Gemini if API key is set,
        otherwise falls back to a mock LLM for fully-offline testing.
        """
        if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your-gemini-api-key":
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.GEMINI_API_KEY)
                return genai.GenerativeModel(
                    model_name=settings.GEMINI_MODEL,
                    system_instruction=self._system_prompt,
                )
            except Exception as e:
                logger.warning("gemini_init_failed_using_mock", error=str(e))
                return None
        else:
            logger.info("no_gemini_key_using_mock_llm", agent=self.agent_id)
            return None

    # ── PII scrubbing ─────────────────────────────────────────────────────────
    def _scrub_pii(self, text: str) -> str:
        """
        Light pre-scrub before sending to external LLM or storing.
        The Dataflow pipeline does a full Presidio scrub downstream,
        but this catches obvious patterns early.

        Patterns scrubbed:
          - SSN-like patterns: XXX-XX-XXXX → [SSN_REDACTED]
          - Credit card numbers: 16-digit sequences → [CC_REDACTED]
          - Email addresses → [EMAIL_REDACTED]
        """
        import re

        # SSN pattern
        text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]", text)
        # Simple credit card (16 digits with optional spaces/dashes)
        text = re.sub(r"\b(?:\d[ -]?){15}\d\b", "[CC_REDACTED]", text)
        # Email
        text = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            "[EMAIL_REDACTED]",
            text,
        )
        return text

    # ── Token estimation ──────────────────────────────────────────────────────
    def _estimate_tokens(self, text: str) -> int:
        """
        Rough token estimate (4 chars ≈ 1 token).
        Replaced by actual token counts when Gemini returns them.
        """
        return max(1, len(text) // 4)

    # ── Main respond method ───────────────────────────────────────────────────
    def respond(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
        session_id: str | None = None,
        interaction_index: int = 0,
        proxy_attr: str = "",
    ) -> AgentResponse:
        """
        Main entry point. Given a prompt, returns a structured AgentResponse
        and publishes telemetry to the pipeline.

        Args:
            prompt:            The user/caller query
            context:           Optional retrieved docs or structured data
            session_id:        Conversation session (multi-turn)
            interaction_index: Ordinal index in this agent's run (0-based)
            proxy_attr:        Synthetic protected proxy attribute for bias testing

        Returns:
            AgentResponse with all interaction metadata
        """
        interaction_id = str(uuid.uuid4())
        session_id = session_id or str(uuid.uuid4())
        span_id = str(uuid.uuid4())[:8]
        start_ts = datetime.now(timezone.utc)
        start_time = time.perf_counter()

        # Build full prompt with context if provided
        full_prompt = prompt
        if context:
            context_str = json.dumps(context, indent=2)
            full_prompt = f"Context:\n{context_str}\n\nQuestion:\n{prompt}"

        # Pre-scrub the prompt
        prompt_redacted = self._scrub_pii(full_prompt)

        log = logger.bind(
            interaction_id=interaction_id,
            agent_id=self.agent_id,
            interaction_index=interaction_index,
        )
        log.info("interaction_start", prompt_preview=prompt[:80])

        # ── Call the LLM ──────────────────────────────────────────────────────
        output_raw = ""
        finish_reason = "stop"
        error_message = ""
        input_tokens = self._estimate_tokens(full_prompt)
        output_tokens = 0

        try:
            output_raw = self._call_llm(full_prompt, log)
            output_tokens = self._estimate_tokens(output_raw)
        except Exception as e:
            finish_reason = "error"
            error_message = str(e)
            output_raw = f"[ERROR: {e}]"
            log.error("llm_call_failed", error=str(e))

        # ── Defect injection ──────────────────────────────────────────────────
        is_defect = False
        defect_type_injected = ""

        if self._should_inject_defect(interaction_index, proxy_attr):
            is_defect = True
            defect_type_injected = self.defect_type
            output_raw = self._apply_defect(prompt, output_raw, interaction_index)
            log.info("defect_injected", defect_type=defect_type_injected)

        # ── Timing ───────────────────────────────────────────────────────────
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # ── Scrub the output ─────────────────────────────────────────────────
        output_redacted = self._scrub_pii(output_raw)

        # ── Build response ────────────────────────────────────────────────────
        response = AgentResponse(
            interaction_id=interaction_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            session_id=session_id,
            interaction_index=interaction_index,
            interaction_ts=start_ts.isoformat(),
            prompt_redacted=prompt_redacted,
            output_redacted=output_redacted,
            output_raw=output_raw,
            system_prompt_hash=self._system_prompt_hash,
            tool_calls=[],
            retrieved_context=json.dumps(context) if context else "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            error_message=error_message,
            synthetic_proxy_attr=proxy_attr,
            is_injected_defect=is_defect,
            injected_defect_type=defect_type_injected,
            model_version_id=self.model_version_id,
            span_id=span_id,
        )

        # ── Publish / store telemetry ─────────────────────────────────────────
        self._publish_telemetry(response)

        log.info(
            "interaction_complete",
            latency_ms=latency_ms,
            is_defect=is_defect,
            tokens=response.total_tokens,
        )

        return response

    # ── LLM call with retry ───────────────────────────────────────────────────
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_llm(self, prompt: str, log) -> str:
        """
        Call the LLM with retry logic. Returns the output string.

        If no LLM client (offline mode), returns a plausible mock response
        so the pipeline can still run end-to-end without API keys.
        """
        if self._llm is None:
            # Mock response for offline development
            return self._mock_response(prompt)

        response = self._llm.generate_content(prompt)
        return response.text

    def _mock_response(self, prompt: str) -> str:
        """
        Return a plausible but generic mock response for offline testing.
        Subclasses can override for more realistic mocks.
        """
        return (
            f"[MOCK RESPONSE — set GEMINI_API_KEY in config/.env for real LLM calls] "
            f"Responding to: {prompt[:100]}..."
        )

    # ── Telemetry publishing ──────────────────────────────────────────────────
    def _publish_telemetry(self, response: AgentResponse) -> None:
        """
        Publish interaction telemetry to:
          - Pub/Sub (if GCP is configured)
          - Local JSON file (always, for LOCAL_MODE and backup)

        The Dataflow pipeline consumes from Pub/Sub and writes to BigQuery.
        Local JSON files are used for offline evaluation and as a safety net.
        """
        payload = response.to_dict()

        # Always write locally (backup + LOCAL_MODE support)
        self._write_local(payload)

        # Publish to Pub/Sub if GCP is configured
        if not settings.LOCAL_MODE and settings.GCP_PROJECT_ID != "your-gcp-project-id":
            self._publish_to_pubsub(payload)

    def _write_local(self, payload: dict[str, Any]) -> None:
        """Write interaction to local JSON file."""
        filename = f"{payload['interaction_id']}.json"
        filepath = self._output_dir / filename
        filepath.write_text(json.dumps(payload, indent=2, default=str))

    def _publish_to_pubsub(self, payload: dict[str, Any]) -> None:
        """Publish to GCP Pub/Sub. Called only when LOCAL_MODE=false."""
        try:
            from google.cloud import pubsub_v1
            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(
                settings.GCP_PROJECT_ID,
                settings.PUBSUB_TOPIC_TELEMETRY,
            )
            data = json.dumps(payload, default=str).encode("utf-8")
            future = publisher.publish(
                topic_path,
                data=data,
                agent_id=self.agent_id,
                interaction_index=str(payload.get("interaction_index", 0)),
            )
            future.result(timeout=10)
        except Exception as e:
            logger.warning("pubsub_publish_failed", error=str(e))
            # Do not raise — local write is the safety net
