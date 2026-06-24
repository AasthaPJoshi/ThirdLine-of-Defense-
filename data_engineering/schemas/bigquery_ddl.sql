-- =============================================================================
-- ThirdLine — BigQuery Schema Definitions
-- =============================================================================
--
-- FILE: data_engineering/schemas/bigquery_ddl.sql
--
-- WHAT THIS FILE DOES:
--   Defines all 7 BigQuery tables that form the ThirdLine data warehouse.
--   Run this once after `terraform apply` to create the schema, OR let
--   the Python ingestion layer create tables dynamically (both work).
--
-- TABLE OVERVIEW:
--   1. dim_agent              — Master record for each AI agent in the fleet
--   2. dim_model_version      — Version history per agent
--   3. fact_agent_interaction — Every interaction (prompt + output) logged
--   4. fact_evaluation        — Per-interaction scores across 5 dimensions
--   5. fact_finding           — Audit findings raised by ThirdLine
--   6. dim_control            — Control catalog (SR 26-2 principles)
--   7. audit_ledger           — Tamper-evident append-only hash chain
--   8. human_review_queue     — Findings awaiting auditor disposition
--
-- HOW TO RUN:
--   bq query --use_legacy_sql=false < data_engineering/schemas/bigquery_ddl.sql
--   OR: terraform apply (creates tables via google_bigquery_table resources)
--
-- INPUT:  None (DDL only)
-- OUTPUT: 8 BigQuery tables in dataset `thirdline`
-- =============================================================================


-- ── 1. dim_agent ─────────────────────────────────────────────────────────────
-- Master record for each AI agent deployed in the institution's fleet.
-- Materiality tier drives how deeply ThirdLine audits the agent:
--   HIGH  → full 5-dimension audit, full-population evidence sampling
--   MEDIUM→ full 5-dimension audit, 50% statistical sample
--   LOW   → hallucination + reliability only, 20% sample
CREATE TABLE IF NOT EXISTS `thirdline.dim_agent` (
    agent_id          STRING    NOT NULL,   -- UUID, primary key
    name              STRING    NOT NULL,   -- human-readable name, e.g. "mortgage-faq-agent"
    description       STRING,               -- what the agent does
    owner_team        STRING,               -- team that owns/deployed the agent
    business_line     STRING,               -- e.g. "Consumer Lending", "Compliance"
    deployment_env    STRING,               -- "production" | "staging" | "sandbox"
    materiality_tier  STRING    NOT NULL,   -- "HIGH" | "MEDIUM" | "LOW"
    tier_rationale    STRING,               -- why this tier was assigned
    first_seen_ts     TIMESTAMP NOT NULL,   -- when telemetry was first received
    last_seen_ts      TIMESTAMP,            -- last telemetry received
    is_active         BOOL      NOT NULL DEFAULT TRUE,
    tags              ARRAY<STRING>,        -- e.g. ["lending", "customer-facing"]
    created_at        TIMESTAMP NOT NULL,
    updated_at        TIMESTAMP NOT NULL
)
PARTITION BY DATE(first_seen_ts)
CLUSTER BY materiality_tier, business_line
OPTIONS (description = "Master record for each AI agent in the institution fleet");


-- ── 2. dim_model_version ─────────────────────────────────────────────────────
-- Tracks every version of every agent. Audits are pinned to a specific version
-- so findings are reproducible even after the agent is updated.
CREATE TABLE IF NOT EXISTS `thirdline.dim_model_version` (
    model_version_id  STRING    NOT NULL,   -- UUID, primary key
    agent_id          STRING    NOT NULL,   -- FK → dim_agent.agent_id
    base_model        STRING    NOT NULL,   -- e.g. "gemini-1.5-flash"
    prompt_hash       STRING    NOT NULL,   -- SHA-256 of the system prompt
    prompt_version    STRING,               -- e.g. "v1.2.3"
    model_card_uri    STRING,               -- path to model card document
    deployed_at       TIMESTAMP NOT NULL,
    deprecated_at     TIMESTAMP,            -- NULL if still active
    is_current        BOOL      NOT NULL DEFAULT TRUE,
    deployment_notes  STRING,
    created_at        TIMESTAMP NOT NULL
)
PARTITION BY DATE(deployed_at)
CLUSTER BY agent_id
OPTIONS (description = "Version history for each agent — audits are pinned to a version");


-- ── 3. fact_agent_interaction ─────────────────────────────────────────────────
-- Core telemetry table. Every single interaction (prompt + output + tool calls)
-- from every agent. PII is redacted before landing here via the Dataflow pipeline.
-- This is the evidence base from which the Evaluation Agent works.
CREATE TABLE IF NOT EXISTS `thirdline.fact_agent_interaction` (
    interaction_id        STRING    NOT NULL,   -- UUID, primary key
    model_version_id      STRING    NOT NULL,   -- FK → dim_model_version
    agent_id              STRING    NOT NULL,   -- denormalised for query performance
    session_id            STRING,               -- conversation session (multi-turn)
    interaction_ts        TIMESTAMP NOT NULL,   -- when the interaction occurred
    prompt_redacted       STRING    NOT NULL,   -- user prompt after PII redaction
    output_redacted       STRING    NOT NULL,   -- agent output after PII redaction
    system_prompt_hash    STRING,               -- hash of system prompt used
    tool_calls_json       JSON,                 -- array of tool calls made by agent
    retrieved_context     STRING,               -- RAG context used (if any)
    input_tokens          INT64,                -- token count of input
    output_tokens         INT64,                -- token count of output
    total_tokens          INT64,                -- total tokens
    latency_ms            INT64,                -- end-to-end latency in milliseconds
    finish_reason         STRING,               -- "stop" | "max_tokens" | "error"
    error_message         STRING,               -- populated if finish_reason = "error"
    synthetic_proxy_attr  STRING,               -- protected proxy attribute (synthetic only)
    is_injected_defect    BOOL      NOT NULL DEFAULT FALSE, -- True for synthetic defects
    injected_defect_type  STRING,               -- "hallucination" | "bias" | etc.
    ingested_at           TIMESTAMP NOT NULL,   -- when the pipeline processed this record
    pipeline_version      STRING                -- version of the Dataflow pipeline
)
PARTITION BY DATE(interaction_ts)
CLUSTER BY agent_id, is_injected_defect
OPTIONS (description = "Every agent interaction — PII redacted — base evidence for evaluation");


-- ── 4. fact_evaluation ────────────────────────────────────────────────────────
-- One row per (interaction, evaluation_dimension). ThirdLine runs up to 5
-- evaluations per interaction. Each evaluation has a score, the rubric version
-- used, the judge model, and supporting evidence.
CREATE TABLE IF NOT EXISTS `thirdline.fact_evaluation` (
    eval_id              STRING    NOT NULL,   -- UUID, primary key
    interaction_id       STRING    NOT NULL,   -- FK → fact_agent_interaction
    agent_id             STRING    NOT NULL,   -- denormalised
    model_version_id     STRING    NOT NULL,   -- denormalised
    eval_run_id          STRING    NOT NULL,   -- groups all evals in a single audit run
    evaluated_at         TIMESTAMP NOT NULL,
    dimension            STRING    NOT NULL,   -- "hallucination" | "bias" | "drift" | "robustness" | "reliability"
    score                FLOAT64   NOT NULL,   -- 0.0–1.0 (higher = better / safer)
    passed               BOOL      NOT NULL,   -- score >= threshold for this dimension
    threshold_used       FLOAT64   NOT NULL,   -- the threshold applied
    rubric_version       STRING    NOT NULL,   -- e.g. "hallucination_v2"
    judge_model          STRING,               -- LLM used as judge (if applicable)
    judge_reasoning      STRING,               -- judge's explanation (for HITL review)
    evidence_snippets    ARRAY<STRING>,        -- interaction excerpts that drove the score
    evidence_uris        ARRAY<STRING>,        -- GCS paths to full evidence artefacts
    deterministic_checks JSON,                 -- results of rule-based checks (non-LLM)
    metadata             JSON                  -- dimension-specific extra fields
)
PARTITION BY DATE(evaluated_at)
CLUSTER BY agent_id, dimension, passed
OPTIONS (description = "Per-interaction evaluation scores across 5 risk dimensions");


-- ── 5. fact_finding ───────────────────────────────────────────────────────────
-- Audit findings raised by ThirdLine. A finding is only raised when the
-- Evaluation Agent detects a failure. The Workpaper Agent drafts the finding;
-- a human auditor must approve before status becomes "APPROVED".
CREATE TABLE IF NOT EXISTS `thirdline.fact_finding` (
    finding_id           STRING    NOT NULL,   -- UUID, primary key
    agent_id             STRING    NOT NULL,   -- FK → dim_agent
    eval_run_id          STRING    NOT NULL,   -- the audit run that raised this finding
    control_id           STRING,               -- FK → dim_control (mapped by Control-Mapping Agent)
    dimension            STRING    NOT NULL,   -- which dimension triggered the finding
    severity             STRING    NOT NULL,   -- "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    title                STRING    NOT NULL,   -- short finding title
    description          STRING    NOT NULL,   -- full finding description (AI-drafted)
    evidence_summary     STRING,               -- summary of supporting evidence
    evidence_interaction_ids ARRAY<STRING>,    -- interactions cited as evidence
    recommended_action   STRING,               -- AI-recommended remediation
    status               STRING    NOT NULL,   -- "PENDING_REVIEW" | "APPROVED" | "REJECTED" | "REMEDIATED"
    drafted_by_agent     STRING    NOT NULL,   -- which agent drafted this (always "workpaper-agent")
    drafted_at           TIMESTAMP NOT NULL,
    reviewed_by_human    STRING,               -- reviewer username
    reviewed_at          TIMESTAMP,
    reviewer_comment     STRING,               -- auditor's notes on approval/rejection
    workpaper_uri        STRING,               -- GCS path to formatted workpaper PDF
    ledger_hash          STRING,               -- SHA-256 of this finding (for ledger)
    created_at           TIMESTAMP NOT NULL,
    updated_at           TIMESTAMP NOT NULL
)
PARTITION BY DATE(drafted_at)
CLUSTER BY agent_id, severity, status
OPTIONS (description = "Audit findings — require human approval before finalisation");


-- ── 6. dim_control ────────────────────────────────────────────────────────────
-- Control catalog. Each control maps to a principle from the regulatory
-- guidance corpus (SR 26-2 / model risk management principles). The
-- Control-Mapping Agent uses RAG to map findings to these controls.
CREATE TABLE IF NOT EXISTS `thirdline.dim_control` (
    control_id        STRING  NOT NULL,   -- e.g. "CTRL-001"
    source_doc        STRING  NOT NULL,   -- e.g. "SR 26-2", "NIST AI RMF"
    principle         STRING  NOT NULL,   -- e.g. "Conceptual Soundness"
    control_name      STRING  NOT NULL,   -- short name
    description       STRING  NOT NULL,   -- full control description
    risk_category     STRING  NOT NULL,   -- "Model Risk" | "Operational Risk" | "Compliance Risk"
    applicable_tiers  ARRAY<STRING>,      -- which materiality tiers this applies to
    testing_guidance  STRING,             -- how ThirdLine tests this control
    remediation_guidance STRING,          -- typical remediation actions
    is_active         BOOL    NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP NOT NULL,
    updated_at        TIMESTAMP NOT NULL
)
OPTIONS (description = "Control catalog mapped to regulatory principles");


-- ── 7. audit_ledger ───────────────────────────────────────────────────────────
-- Tamper-evident, append-only audit trail. Every approved finding is hashed
-- and chained to the previous entry. Any modification to a historical entry
-- breaks the chain and is immediately detectable.
-- This is the examiner-ready evidence that proves ThirdLine's integrity.
CREATE TABLE IF NOT EXISTS `thirdline.audit_ledger` (
    seq               INT64     NOT NULL,   -- auto-incrementing sequence number
    finding_id        STRING    NOT NULL,   -- FK → fact_finding
    agent_id          STRING    NOT NULL,   -- denormalised for quick lookup
    event_type        STRING    NOT NULL,   -- "FINDING_APPROVED" | "FINDING_REJECTED" | "FINDING_REMEDIATED"
    actor             STRING    NOT NULL,   -- who performed the action (username or "system")
    action_detail     STRING,               -- additional detail about the action
    finding_hash      STRING    NOT NULL,   -- SHA-256 of the finding content at this point
    prev_hash         STRING    NOT NULL,   -- SHA-256 of previous ledger entry (chain link)
    chain_hash        STRING    NOT NULL,   -- SHA-256(prev_hash + finding_hash) — the chain
    event_ts          TIMESTAMP NOT NULL,   -- when this event occurred
    metadata          JSON                  -- any additional metadata
)
PARTITION BY DATE(event_ts)
CLUSTER BY agent_id
OPTIONS (description = "Tamper-evident append-only audit ledger — hash-chained for integrity");


-- ── 8. human_review_queue ─────────────────────────────────────────────────────
-- Staging table for findings awaiting human auditor review.
-- The API reads from this table to populate the HITL dashboard.
-- Once a human disposes (approve/reject), the row is updated and the
-- finding is moved to fact_finding with its final status.
CREATE TABLE IF NOT EXISTS `thirdline.human_review_queue` (
    queue_id          STRING    NOT NULL,   -- UUID
    finding_id        STRING    NOT NULL,   -- FK → fact_finding
    agent_id          STRING    NOT NULL,
    severity          STRING    NOT NULL,
    title             STRING    NOT NULL,
    draft_text        STRING    NOT NULL,   -- full workpaper draft for review
    evidence_uris     ARRAY<STRING>,        -- links to evidence artefacts
    control_id        STRING,
    dimension         STRING,
    assigned_to       STRING,               -- username of assigned auditor (or NULL = unassigned)
    queued_at         TIMESTAMP NOT NULL,
    sla_deadline      TIMESTAMP,            -- by when the auditor should act (e.g. 24h for CRITICAL)
    status            STRING    NOT NULL,   -- "PENDING" | "IN_REVIEW" | "ACTIONED"
    actioned_at       TIMESTAMP,
    actioned_by       STRING
)
PARTITION BY DATE(queued_at)
CLUSTER BY severity, status
OPTIONS (description = "HITL queue — findings awaiting human auditor disposition");
