"""
=============================================================================
ThirdLine — Audit Runner Script
=============================================================================

FILE: scripts/run_audit.py

WHAT THIS FILE DOES:
    Main entry point for Day 2. Triggers the full 6-step audit pipeline
    orchestrated by the AuditOrchestrator. After this script completes,
    all findings are in the human_review_queue waiting for auditor action.

HOW TO RUN:
    python scripts/run_audit.py                     # audit all agents
    python scripts/run_audit.py --agent agt-mortgage-faq-001
    python scripts/run_audit.py --dimensions hallucination robustness

INPUT:  data/interactions/ (from Day 1 run_fleet.py)
OUTPUT: data/findings/     (findings + workpapers + review queue + ledger)
=============================================================================
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from assurance_agents.adk.orchestrator import AuditOrchestrator

def main():
    parser = argparse.ArgumentParser(description="ThirdLine Audit Pipeline")
    parser.add_argument("--agent", default="all")
    parser.add_argument("--dimensions", nargs="*",
                        default=["hallucination", "bias", "drift", "robustness", "reliability"])
    args = parser.parse_args()

    orchestrator = AuditOrchestrator()
    orchestrator.run({
        "agent_id": args.agent,
        "dimensions": args.dimensions,
    })

if __name__ == "__main__":
    main()
