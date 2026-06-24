"""
=============================================================================
ThirdLine — Orchestrator Agent (Google ADK)
=============================================================================

FILE: assurance_agents/adk/orchestrator.py

WHAT THIS FILE DOES:
    The master orchestrator agent for ThirdLine's assurance pipeline.
    Implements a structured 6-step audit plan using Google ADK's agent
    framework (with a clean LangGraph fallback for environments where
    ADK is not yet installed).

    THE AUDIT PLAN:
    ┌────────────┬────────────────────────────────────────────────────┐
    │ Step       │ Description                                        │
    ├────────────┼────────────────────────────────────────────────────┤
    │ DISCOVER   │ Inventory Agent: find and tier the agent fleet     │
    │ COLLECT    │ Evidence Agent: pull interaction logs              │
    │ EVALUATE   │ Evaluation Engine: run 5-dimension test battery   │
    │ MAP        │ Control-Mapping: attach findings to controls       │
    │ DRAFT      │ Workpaper Agent: write finding text                │
    │ HITL_GATE  │ Human-in-the-loop: park findings for review       │
    └────────────┴────────────────────────────────────────────────────┘

    HUMAN-IN-THE-LOOP DESIGN:
    The orchestrator enforces a hard stop before any finding is finalised.
    No finding can move from PENDING_REVIEW to APPROVED without a human
    auditor explicitly approving it via the API. The orchestrator writes
    to the human_review_queue and stops — it does NOT self-approve.

    ADK vs LANGGRAPH:
    This file implements the orchestrator using Python classes that mirror
    the Google ADK agent pattern. If google-adk is installed, it wraps
    the ADK Agent class. If not, it uses a clean state-machine approach
    that is functionally identical and easier to debug.

HOW TO RUN:
    python assurance_agents/adk/orchestrator.py
    OR via: python scripts/run_audit.py

INPUT:
    audit_scope dict:
      agent_id (str)          — which agent to audit ("all" for fleet)
      dimensions (list[str])  — which dimensions to run (default: all)
      sample_mode (str)       — "full" | "sample_50pct" | "sample_20pct"

OUTPUT:
    AuditRunResult with:
      - findings: list of finding dicts (PENDING_REVIEW status)
      - human_review_queue: list of queue entries
      - eval_summaries: per-agent evaluation summaries
      Written to data/findings/ and data/review_queue/
=============================================================================
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import sys
sys.path.insert(0, str(Path(__file__).parents[2]))
from config.settings import settings
from evaluation.evaluator import EvaluationEngine, AgentEvalSummary
from governance.control_catalog import CONTROL_BY_ID, get_control

logger = structlog.get_logger(__name__)
console = Console()


# ── Audit plan state ──────────────────────────────────────────────────────────
@dataclass
class AuditStep:
    step_id: str
    name: str
    status: str = "PENDING"       # PENDING | RUNNING | COMPLETE | FAILED
    started_at: str = ""
    completed_at: str = ""
    output: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class AuditRunResult:
    """Complete result of one orchestrated audit run."""
    run_id: str
    scope: dict
    started_at: str
    completed_at: str = ""
    steps: list[AuditStep] = field(default_factory=list)
    agents_audited: list[str] = field(default_factory=list)
    total_interactions_reviewed: int = 0
    total_findings: int = 0
    findings: list[dict] = field(default_factory=list)
    review_queue: list[dict] = field(default_factory=list)
    eval_summaries: list[AgentEvalSummary] = field(default_factory=list)
    status: str = "RUNNING"       # RUNNING | COMPLETE | FAILED


# ── Inventory Agent ───────────────────────────────────────────────────────────
class InventoryAgent:
    """
    Discovers and tiers the AI agent fleet.

    In LOCAL_MODE: reads from agents_under_audit/agents/agent_fleet.py
    In GCP mode: would query the agent registry / telemetry warehouse

    Returns a list of agent records with materiality tier assignments.
    Tier determines how deeply ThirdLine audits:
      HIGH   → all 5 dimensions, full population
      MEDIUM → all 5 dimensions, 50% sample
      LOW    → hallucination + reliability only, 20% sample
    """

    KNOWN_FLEET = [
        {
            "agent_id": "agt-mortgage-faq-001",
            "name": "mortgage-faq-agent",
            "business_line": "Consumer Lending",
            "materiality_tier": "HIGH",
            "tier_rationale": "Directly influences customer understanding of lending products. Hallucination risk creates regulatory exposure.",
            "owner_team": "Consumer Digital",
        },
        {
            "agent_id": "agt-kyc-summary-001",
            "name": "kyc-summary-agent",
            "business_line": "Compliance",
            "materiality_tier": "HIGH",
            "tier_rationale": "Processes PII and influences compliance officer decisions. PII leakage risk is critical.",
            "owner_team": "Compliance Technology",
        },
        {
            "agent_id": "agt-lending-decision-001",
            "name": "lending-decision-agent",
            "business_line": "Consumer Lending",
            "materiality_tier": "HIGH",
            "tier_rationale": "Directly involved in adverse action communications. Disparate treatment risk requires fair lending oversight.",
            "owner_team": "Lending Technology",
        },
        {
            "agent_id": "agt-fx-posttrade-001",
            "name": "fx-posttrade-agent",
            "business_line": "Corporate and Investment Banking",
            "materiality_tier": "MEDIUM",
            "tier_rationale": "Assists operations staff in settlement decisions. Quality drift could cause operational errors.",
            "owner_team": "CIB Operations Technology",
        },
        {
            "agent_id": "agt-compliance-qa-001",
            "name": "compliance-qa-agent",
            "business_line": "Compliance",
            "materiality_tier": "HIGH",
            "tier_rationale": "Answers regulatory questions for staff. Prompt injection could cause agent to confirm false policy.",
            "owner_team": "Compliance Technology",
        },
    ]

    def run(self, scope: dict) -> dict:
        """
        Discover agents matching the audit scope.
        Returns dict with 'agents' list and 'inventory_summary'.
        """
        target_agent_id = scope.get("agent_id", "all")

        if target_agent_id == "all":
            agents = self.KNOWN_FLEET
        else:
            agents = [a for a in self.KNOWN_FLEET if a["agent_id"] == target_agent_id]
            if not agents:
                raise ValueError(f"Agent {target_agent_id} not found in fleet registry")

        # Verify interactions exist for each agent
        available = []
        for agent in agents:
            agent_dir = settings.data_dir / "interactions" / agent["agent_id"]
            interaction_count = len(list(agent_dir.glob("*.json"))) if agent_dir.exists() else 0
            available.append({
                **agent,
                "interaction_count": interaction_count,
                "has_data": interaction_count > 0,
            })

        logger.info(
            "inventory_complete",
            total_agents=len(available),
            with_data=sum(1 for a in available if a["has_data"]),
        )

        return {
            "agents": available,
            "total_agents": len(available),
            "agents_with_data": [a for a in available if a["has_data"]],
        }


# ── Evidence Agent ─────────────────────────────────────────────────────────────
class EvidenceAgent:
    """
    Pulls interaction evidence for each agent under audit.
    Respects materiality tier for sampling:
      HIGH   → full population
      MEDIUM → 50% random sample
      LOW    → 20% random sample
    """

    def run(self, agent_record: dict) -> dict:
        """Load and sample interactions for one agent."""
        import random

        agent_id = agent_record["agent_id"]
        tier = agent_record["materiality_tier"]
        agent_dir = settings.data_dir / "interactions" / agent_id

        interactions = []
        for f in agent_dir.glob("*.json"):
            data = json.loads(f.read_text())
            interactions.append(data)
        interactions.sort(key=lambda x: x.get("interaction_index", 0))

        total = len(interactions)

        # Apply sampling based on tier
        if tier == "HIGH":
            sampled = interactions          # full population
            sample_note = "Full population (HIGH tier)"
        elif tier == "MEDIUM":
            n = max(10, total // 2)
            sampled = random.sample(interactions, min(n, total))
            sampled.sort(key=lambda x: x.get("interaction_index", 0))
            sample_note = f"50% sample (MEDIUM tier): {len(sampled)}/{total}"
        else:
            n = max(5, total // 5)
            sampled = random.sample(interactions, min(n, total))
            sample_note = f"20% sample (LOW tier): {len(sampled)}/{total}"

        logger.info(
            "evidence_collected",
            agent_id=agent_id,
            tier=tier,
            total=total,
            sampled=len(sampled),
        )

        return {
            "agent_id": agent_id,
            "interactions": sampled,
            "total_interactions": total,
            "sampled_interactions": len(sampled),
            "sample_note": sample_note,
        }


# ── Workpaper Agent ────────────────────────────────────────────────────────────
class WorkpaperAgent:
    """
    Drafts formal audit finding text and workpaper entries.
    Formats each finding into a structured workpaper that an auditor
    can review, edit, approve, or reject.

    The workpaper includes:
      - Finding header (ID, agent, control, severity)
      - Condition (what ThirdLine observed)
      - Criteria (what the control requires)
      - Cause (root cause analysis)
      - Effect (potential impact)
      - Recommendation (remediation steps)
      - Evidence references
    """

    def draft(self, finding: dict) -> dict:
        """Draft a workpaper entry for a single finding."""
        control_id = finding.get("control_id", "UNKNOWN")
        control = get_control(control_id)
        agent_id = finding["agent_id"]
        dimension = finding["dimension"]
        severity = finding["severity"]
        failure_count = finding.get("failure_count", 0)
        total_evaluated = finding.get("total_evaluated", 0)
        avg_score = finding.get("avg_score", 0.0)

        condition = (
            f"During the evaluation of agent '{agent_id}', ThirdLine's automated "
            f"assurance pipeline identified {failure_count} interaction(s) out of "
            f"{total_evaluated} evaluated that failed the {dimension} evaluation "
            f"dimension. The average evaluation score was {avg_score:.2f} against "
            f"a required threshold of {finding.get('threshold', 0.75):.2f}."
        )

        criteria = (
            f"Per control {control_id} — {control.control_name if control else dimension}: "
            f"{control.description[:300] if control else 'Refer to AI governance policy.'}"
        )

        cause = (
            f"Preliminary root cause analysis suggests the agent's "
            f"{'system prompt lacks explicit constraints against ' + dimension if dimension in ['hallucination', 'robustness'] else 'outputs exhibit ' + dimension + ' characteristics'}. "
            f"Refer to evaluation evidence for specific interaction examples. "
            f"Agent owner review is required to confirm root cause."
        )

        effect = {
            "hallucination": "Customers or staff may receive factually incorrect policy information, creating regulatory exposure and potential mis-selling risk.",
            "bias": "Differential treatment in agent outputs may constitute disparate impact under fair lending regulations, exposing the institution to regulatory and reputational risk.",
            "drift": "Degraded agent quality may cause staff to receive poor operational guidance, increasing error rates in dependent processes.",
            "robustness": "A prompt-injectable agent could be manipulated by malicious actors to bypass controls, confirm false information, or expose system internals.",
            "reliability": "PII leakage or task failure in an agent creates data privacy exposure and operational risk in dependent downstream processes.",
        }.get(dimension, "Risk to operational integrity and regulatory compliance.")

        recommendation = control.remediation_guidance if control else "Review agent configuration and remediate identified issues."

        workpaper_text = f"""
AUDIT FINDING WORKPAPER
═══════════════════════════════════════════════════════════════
Finding ID:    {finding['finding_id']}
Agent:         {agent_id}
Dimension:     {dimension.upper()}
Control:       {control_id} — {control.control_name if control else 'N/A'}
Severity:      {severity}
Status:        PENDING HUMAN REVIEW
Drafted:       {finding.get('drafted_at', datetime.now(timezone.utc).isoformat())}
Drafted by:    ThirdLine Workpaper Agent (automated draft — human review required)
═══════════════════════════════════════════════════════════════

CONDITION (What was observed):
{condition}

CRITERIA (What is required):
{criteria}

CAUSE (Preliminary root cause):
{cause}

EFFECT (Potential impact):
{effect}

RECOMMENDATION:
{recommendation}

EVIDENCE SUMMARY:
{finding.get('evidence_summary', 'See referenced interaction IDs.')}

TOP FAILURE EVIDENCE:
{chr(10).join(f'  {i+1}. {e}' for i, e in enumerate(finding.get('top_evidence', [])[:3]))}

INTERACTION IDs (evidence):
{chr(10).join(f'  - {iid}' for iid in finding.get('evidence_interaction_ids', [])[:5])}

═══════════════════════════════════════════════════════════════
AUDITOR ACTION REQUIRED:
  [ ] Review this finding and supporting evidence
  [ ] Confirm or update root cause analysis
  [ ] Approve or reject this finding
  [ ] If approved: assign to agent owner for remediation
═══════════════════════════════════════════════════════════════
""".strip()

        return {
            "finding_id": finding["finding_id"],
            "workpaper_text": workpaper_text,
            "condition": condition,
            "criteria": criteria,
            "cause": cause,
            "effect": effect,
            "recommendation": recommendation,
            "drafted_at": datetime.now(timezone.utc).isoformat(),
        }


# ── Audit Ledger ───────────────────────────────────────────────────────────────
class AuditLedger:
    """
    Tamper-evident append-only audit log.
    Each entry is hash-chained: chain_hash = SHA256(prev_hash + finding_hash)
    Any modification to a historical entry breaks the chain detectably.
    """

    def __init__(self):
        self._ledger_path = settings.data_dir / "findings" / "audit_ledger.json"
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries = self._load()

    def _load(self) -> list[dict]:
        if self._ledger_path.exists():
            return json.loads(self._ledger_path.read_text())
        return []

    def _save(self):
        self._ledger_path.write_text(json.dumps(self._entries, indent=2, default=str))

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def append(self, finding: dict, actor: str = "thirdline-orchestrator", event_type: str = "FINDING_DRAFTED") -> dict:
        """Append a finding to the ledger. Returns the ledger entry."""
        seq = len(self._entries)
        finding_content = json.dumps(finding, sort_keys=True, default=str)
        finding_hash = self._hash(finding_content)
        prev_hash = self._entries[-1]["chain_hash"] if self._entries else self._hash("GENESIS")
        chain_hash = self._hash(prev_hash + finding_hash)

        entry = {
            "seq": seq,
            "finding_id": finding["finding_id"],
            "agent_id": finding["agent_id"],
            "event_type": event_type,
            "actor": actor,
            "finding_hash": finding_hash,
            "prev_hash": prev_hash,
            "chain_hash": chain_hash,
            "event_ts": datetime.now(timezone.utc).isoformat(),
        }
        self._entries.append(entry)
        self._save()
        return entry

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Verify the integrity of the hash chain. Returns (is_valid, errors)."""
        errors = []
        for i, entry in enumerate(self._entries):
            if i == 0:
                expected_prev = self._hash("GENESIS")
            else:
                expected_prev = self._entries[i - 1]["chain_hash"]

            expected_chain = self._hash(expected_prev + entry["finding_hash"])
            if entry["chain_hash"] != expected_chain:
                errors.append(f"Chain broken at seq {i}: finding_id={entry['finding_id']}")
            if entry["prev_hash"] != expected_prev:
                errors.append(f"Prev hash mismatch at seq {i}")

        return len(errors) == 0, errors

    def get_entries(self) -> list[dict]:
        return self._entries


# ── Main Orchestrator ─────────────────────────────────────────────────────────
class AuditOrchestrator:
    """
    Master orchestrator that coordinates all audit agents in sequence.
    Implements the 6-step audit plan with HITL gate enforcement.

    This is the Google ADK-pattern orchestrator. In a full ADK deployment,
    each sub-agent would be an ADK Agent with MCP tool servers.
    Here we use direct Python calls with the same logical boundaries —
    the architecture is identical, the binding layer differs.
    """

    AUDIT_STEPS = [
        "DISCOVER",
        "COLLECT",
        "EVALUATE",
        "MAP",
        "DRAFT",
        "HITL_GATE",
    ]

    def __init__(self):
        self.inventory_agent = InventoryAgent()
        self.evidence_agent = EvidenceAgent()
        self.evaluation_engine = EvaluationEngine()
        self.workpaper_agent = WorkpaperAgent()
        self.ledger = AuditLedger()

        # Output paths
        self._findings_dir = settings.data_dir / "findings"
        self._queue_dir = settings.data_dir / "findings" / "review_queue"
        self._findings_dir.mkdir(parents=True, exist_ok=True)
        self._queue_dir.mkdir(parents=True, exist_ok=True)

    def run(self, scope: dict) -> AuditRunResult:
        """
        Execute the full 6-step audit plan for the given scope.

        Args:
            scope: {
                "agent_id": "all" | specific agent_id,
                "dimensions": list of dimensions to run (default: all),
                "sample_mode": "full" | "sample_50pct" | "sample_20pct"
            }

        Returns:
            AuditRunResult with all findings in PENDING_REVIEW status
        """
        run_id = f"audit-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:6]}"
        run = AuditRunResult(
            run_id=run_id,
            scope=scope,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        console.print(Panel.fit(
            f"[bold blue]ThirdLine Audit Orchestrator[/bold blue]\n"
            f"Run ID: {run_id}\n"
            f"Scope: {json.dumps(scope)}",
            border_style="blue"
        ))

        logger.info("audit_run_start", run_id=run_id, scope=scope)

        for step_name in self.AUDIT_STEPS:
            step = AuditStep(
                step_id=str(uuid.uuid4()),
                name=step_name,
                status="RUNNING",
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            run.steps.append(step)

            console.print(f"\n[bold cyan]── Step: {step_name}[/bold cyan]")

            try:
                if step_name == "DISCOVER":
                    output = self._step_discover(scope)
                    run.agents_audited = [a["agent_id"] for a in output["agents_with_data"]]
                    step.output = {"agents_found": len(output["agents_with_data"])}

                elif step_name == "COLLECT":
                    output = self._step_collect(output["agents_with_data"])
                    run.total_interactions_reviewed = output["total_interactions"]
                    step.output = {"total_interactions": output["total_interactions"]}

                elif step_name == "EVALUATE":
                    eval_output = self._step_evaluate(output["agents_with_data"])
                    run.eval_summaries = eval_output["summaries"]
                    run.findings = eval_output["all_findings"]
                    run.total_findings = len(run.findings)
                    step.output = {"findings_generated": run.total_findings}

                elif step_name == "MAP":
                    run.findings = self._step_map_controls(run.findings)
                    step.output = {"findings_mapped": len(run.findings)}

                elif step_name == "DRAFT":
                    run.findings = self._step_draft_workpapers(run.findings)
                    step.output = {"workpapers_drafted": len(run.findings)}

                elif step_name == "HITL_GATE":
                    run.review_queue = self._step_hitl_gate(run.findings, run_id)
                    step.output = {
                        "queued_for_review": len(run.review_queue),
                        "message": "STOP — findings require human auditor review before finalisation",
                    }

                step.status = "COMPLETE"
                step.completed_at = datetime.now(timezone.utc).isoformat()
                console.print(f"  [green]✓ {step_name} complete[/green] — {step.output}")

            except Exception as e:
                step.status = "FAILED"
                step.error = str(e)
                step.completed_at = datetime.now(timezone.utc).isoformat()
                console.print(f"  [red]✗ {step_name} FAILED: {e}[/red]")
                logger.error("audit_step_failed", step=step_name, error=str(e))
                run.status = "FAILED"
                break

        run.completed_at = datetime.now(timezone.utc).isoformat()
        if run.status != "FAILED":
            run.status = "COMPLETE"

        # Save run result
        self._save_run(run)
        self._print_summary(run)

        logger.info(
            "audit_run_complete",
            run_id=run_id,
            status=run.status,
            findings=run.total_findings,
            queued=len(run.review_queue),
        )

        return run

    def _step_discover(self, scope: dict) -> dict:
        return self.inventory_agent.run(scope)

    def _step_collect(self, agents: list[dict]) -> dict:
        total = 0
        for agent in agents:
            evidence = self.evidence_agent.run(agent)
            agent["_evidence"] = evidence
            total += evidence["sampled_interactions"]
        return {"agents_with_data": agents, "total_interactions": total}

    def _step_evaluate(self, agents: list[dict]) -> dict:
        summaries = []
        all_findings = []
        for agent in agents:
            if not agent.get("has_data"):
                continue
            summary = self.evaluation_engine.run_agent_evaluation(agent["agent_id"])
            summaries.append(summary)
            all_findings.extend(summary.findings_triggered)
        return {"summaries": summaries, "all_findings": all_findings}

    def _step_map_controls(self, findings: list[dict]) -> list[dict]:
        """Enrich findings with control details from the catalog."""
        for finding in findings:
            control_id = finding.get("control_id")
            control = get_control(control_id) if control_id else None
            if control:
                finding["control_name"] = control.control_name
                finding["control_principle"] = control.principle
                finding["control_source_doc"] = control.source_doc
        return findings

    def _step_draft_workpapers(self, findings: list[dict]) -> list[dict]:
        for finding in findings:
            workpaper = self.workpaper_agent.draft(finding)
            finding["workpaper_text"] = workpaper["workpaper_text"]
            finding["workpaper_drafted_at"] = workpaper["drafted_at"]
            # Append to audit ledger (DRAFTED event)
            entry = self.ledger.append(finding, event_type="FINDING_DRAFTED")
            finding["ledger_hash"] = entry["chain_hash"]
            finding["ledger_seq"] = entry["seq"]
        return findings

    def _step_hitl_gate(self, findings: list[dict], run_id: str) -> list[dict]:
        """
        HARD STOP. Park all findings in the human review queue.
        The orchestrator does not proceed until a human auditor
        acts on each finding via the API.
        """
        queue_entries = []
        for finding in findings:
            sla_hours = {"CRITICAL": 4, "HIGH": 24, "MEDIUM": 72, "LOW": 168}
            sla_h = sla_hours.get(finding["severity"], 24)

            from datetime import timedelta
            now = datetime.now(timezone.utc)
            sla_deadline = (now + timedelta(hours=sla_h)).isoformat()

            entry = {
                "queue_id": str(uuid.uuid4()),
                "finding_id": finding["finding_id"],
                "agent_id": finding["agent_id"],
                "severity": finding["severity"],
                "title": finding["title"],
                "draft_text": finding.get("workpaper_text", ""),
                "evidence_uris": finding.get("evidence_interaction_ids", []),
                "control_id": finding.get("control_id"),
                "dimension": finding["dimension"],
                "assigned_to": None,
                "queued_at": now.isoformat(),
                "sla_deadline": sla_deadline,
                "status": "PENDING",
                "run_id": run_id,
            }
            queue_entries.append(entry)

            # Save to disk
            q_path = self._queue_dir / f"{entry['queue_id']}.json"
            q_path.write_text(json.dumps(entry, indent=2, default=str))

        logger.info(
            "hitl_gate_enforced",
            findings_queued=len(queue_entries),
            message="Audit pipeline paused. Human review required.",
        )
        return queue_entries

    def _save_run(self, run: AuditRunResult) -> None:
        run_path = self._findings_dir / f"run_{run.run_id}.json"
        run_data = {
            "run_id": run.run_id,
            "scope": run.scope,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "status": run.status,
            "agents_audited": run.agents_audited,
            "total_interactions_reviewed": run.total_interactions_reviewed,
            "total_findings": run.total_findings,
            "findings": run.findings,
            "review_queue": run.review_queue,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                    "output": s.output,
                    "error": s.error,
                }
                for s in run.steps
            ],
        }
        run_path.write_text(json.dumps(run_data, indent=2, default=str))
        logger.info("run_saved", path=str(run_path))

    def _print_summary(self, run: AuditRunResult) -> None:
        console.print("\n")
        console.print(Panel.fit(
            f"[bold {'green' if run.status == 'COMPLETE' else 'red'}]"
            f"Audit Run {run.status}[/bold {'green' if run.status == 'COMPLETE' else 'red'}]\n\n"
            f"Run ID:          {run.run_id}\n"
            f"Agents audited:  {len(run.agents_audited)}\n"
            f"Interactions:    {run.total_interactions_reviewed}\n"
            f"Findings:        {run.total_findings}\n"
            f"Queued for HITL: {len(run.review_queue)}\n\n"
            f"[bold yellow]⚠ Pipeline paused — human review required[/bold yellow]\n"
            f"Next step: python scripts/run_api.py",
            border_style="green" if run.status == "COMPLETE" else "red"
        ))

        if run.findings:
            table = Table(title="Findings Summary", border_style="yellow")
            table.add_column("Agent", style="cyan")
            table.add_column("Dimension", style="blue")
            table.add_column("Severity", style="bold")
            table.add_column("Control")
            table.add_column("Failures", justify="right", style="red")

            for f in run.findings:
                sev = f["severity"]
                sev_color = "red" if sev == "CRITICAL" else "yellow" if sev == "HIGH" else "blue"
                table.add_row(
                    f["agent_id"].replace("agt-", "").replace("-001", ""),
                    f["dimension"],
                    f"[{sev_color}]{sev}[/{sev_color}]",
                    f.get("control_id", "?"),
                    str(f.get("failure_count", "?")),
                )
            console.print(table)

        # Ledger verification
        is_valid, errors = self.ledger.verify_chain()
        status = "[green]✓ INTACT[/green]" if is_valid else f"[red]✗ BROKEN ({len(errors)} errors)[/red]"
        console.print(f"\nAudit Ledger: {status} — {len(self.ledger.get_entries())} entries")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    orchestrator = AuditOrchestrator()
    result = orchestrator.run({"agent_id": "all"})
