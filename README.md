# ThirdLine — Agentic AI Audit & Governance Platform

> **"Who audits the agents?"**
> ThirdLine is a production-grade, cloud-native platform that continuously discovers,
> tests, and produces audit-ready evidence on a financial institution's deployed AI
> agent fleet — catching hallucination, bias, drift, and security vulnerabilities
> before regulators do.

---

## Why This Exists

Modern financial institutions are deploying AI agents at scale — customer service
bots, lending decision aids, KYC summarizers, trade triage systems. Each of these
agents makes or shapes decisions that affect real customers and carry regulatory
exposure. Yet most institutions have no automated, independent mechanism to verify
that these agents are accurate, fair, and in control.

ThirdLine fills that gap. It is the **Third Line of Defense** for the agentic era:
an autonomous assurance system that audits AI agents the way internal audit teams
audit any other high-risk process — with evidence, controls mapping, documented
findings, and mandatory human sign-off.

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│            AGENTS UNDER AUDIT (synthetic fleet)              │
│  mortgage-faq · kyc-summary · lending-decision               │
│  fx-posttrade · compliance-qa                                │
└────────────────────┬────────────────────────────────────────┘
                     │ OpenTelemetry GenAI spans
                     ▼
            [Pub/Sub Topic]
                     │
                     ▼
        [Dataflow / Apache Beam]
         PII redaction + enrich
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
   [Cloud Storage]         [BigQuery]
   raw landing             warehouse + ledger
                               │
                           [dbt Core]
                         transforms + tests
                               │
                     ┌─────────┴──────────┐
                     ▼                    ▼
          [Orchestrator Agent]     [Vertex AI / Gemini]
          Google ADK + MCP         reasoning + judge
               │
    ┌──────────┼──────────────────┬──────────────┐
    ▼          ▼                  ▼              ▼
[Inventory] [Evidence]     [Evaluation]   [Control-Map]
  Agent       Agent           Agent          Agent
                                               │
                                        [Workpaper Agent]
                                               │
                                    [Human Review Queue]
                                         HITL gate
                                               │
                                    [Audit Ledger — hash-chained]
                                               │
                               ┌───────────────┴──────────┐
                               ▼                          ▼
                        [FastAPI / Cloud Run]      [React Dashboard]
```

---

## Real Metrics (fill after Day 3 run)

| Metric | Value |
|--------|-------|
| Agents audited | 5 synthetic agents |
| Interactions tested | 250 (50 per agent) |
| Defect types injected | 5 (hallucination, bias, drift, robustness, reliability) |
| Overall detection F1 | [fill after run] |
| Precision | [fill after run] |
| Recall | [fill after run] |
| Judge–Human agreement (κ) | [fill after run] |

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Cloud | GCP — Cloud Storage, BigQuery, Pub/Sub, Dataflow, Cloud Run, Vertex AI |
| Agentic | Google ADK, MCP (Model Context Protocol), Vertex AI / Gemini |
| Data engineering | Apache Beam, dbt Core, Great Expectations, PySpark |
| Orchestration | Cloud Composer / Airflow |
| Classical ML | Isolation Forest, XGBoost, SHAP, PSI |
| LLM evaluation | LLM-as-judge (versioned rubrics), red-team suite, RAG faithfulness |
| API | FastAPI (Cloud Run) |
| Frontend | React + TypeScript |
| IaC | Terraform |
| CI/CD | GitHub Actions + Cloud Build |
| Observability | Cloud Logging, OpenTelemetry, Cloud Monitoring |

---

## Quick Start (Mac)

```bash
# 1. Clone and enter
git clone https://github.com/YOUR_USERNAME/thirdline.git
cd thirdline

# 2. Run the full Mac setup script
chmod +x scripts/mac_setup.sh
./scripts/mac_setup.sh

# 3. Activate environment
source venv/bin/activate

# 4. Copy and fill environment variables
cp config/.env.example config/.env
# Edit config/.env with your GCP project ID and keys

# 5. Run the synthetic fleet (generates 250 interactions)
python scripts/run_fleet.py

# 6. Run the audit pipeline
python scripts/run_audit.py

# 7. Start the API
uvicorn api.main:app --reload

# 8. Start the dashboard (separate terminal)
cd frontend && npm run dev
```

---

## Repository Structure

```
thirdline/
├── README.md
├── requirements.txt
├── config/
│   ├── .env.example
│   └── settings.py
├── scripts/
│   ├── mac_setup.sh          # One-command Mac dev setup
│   ├── run_fleet.py          # Runs all 5 synthetic agents
│   └── run_audit.py          # Triggers full audit pipeline
├── infra/terraform/          # GCP infrastructure as code
├── data_engineering/
│   ├── beam/                 # Dataflow pipeline
│   ├── dbt/                  # Transforms, tests, lineage
│   ├── schemas/              # BigQuery DDL
│   └── quality/              # Great Expectations
├── agents_under_audit/       # 5 synthetic bank agents + defects
├── assurance_agents/
│   ├── adk/                  # Google ADK multi-agent system
│   └── mcp_servers/          # MCP tool servers
├── evaluation/
│   ├── rubrics/              # Versioned LLM-as-judge rubrics
│   └── redteam/              # Adversarial prompt payloads
├── api/                      # FastAPI backend
├── governance/               # SR 26-2 corpus, model cards
├── docs/                     # Architecture diagrams, examiner pack
└── .github/workflows/        # CI/CD
```

---

## Project Principles

1. **Ground truth first** — every defect is injected with a known label so detection metrics are real
2. **Human in the loop** — no finding is finalized without auditor approval
3. **Evidence-gated** — agents cannot raise a finding without citing specific interaction evidence
4. **Validate the validator** — ThirdLine includes a model card for itself
5. **Synthetic only** — zero real customer PII at any layer

---

*Built to demonstrate production-grade AI governance for the audit function of a modern financial institution.*
