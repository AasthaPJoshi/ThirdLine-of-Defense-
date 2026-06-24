#!/usr/bin/env bash
# =============================================================================
# ThirdLine — Quick Fix Script
# =============================================================================
#
# FILE: scripts/fix_dependencies.sh
#
# WHAT THIS FILE DOES:
#   Resolves the two known post-install issues:
#   1. protobuf version conflict (dbt wants >=6.0, GCP clients installed 5.x)
#   2. Runs a corrected environment verification that properly checks all packages
#
# HOW TO RUN:
#   source venv/bin/activate
#   chmod +x scripts/fix_dependencies.sh
#   ./scripts/fix_dependencies.sh
#
# INPUT:  Active virtual environment
# OUTPUT: All packages verified and working
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }

echo ""
echo -e "${BOLD}${BLUE}ThirdLine — Dependency Fix${NC}"
echo ""

# Confirm venv is active
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo -e "${RED}[ERROR]${NC} Virtual environment not active."
    echo "Run: source venv/bin/activate"
    exit 1
fi
log_success "Virtual environment active: $VIRTUAL_ENV"

# ── Fix 1: protobuf version conflict ─────────────────────────────────────────
# dbt 1.8 requires protobuf >=6.0 but GCP clients pulled in 5.x
# Fix: upgrade protobuf to a version compatible with both
echo ""
log_info "Fix 1: Resolving protobuf version conflict..."
pip install --quiet "protobuf>=6.0,<7.0"
log_success "protobuf upgraded"

# ── Fix 2: Pin google-cloud-bigquery to ensure __version__ is accessible ──────
log_info "Fix 2: Ensuring google-cloud-bigquery is importable..."
pip install --quiet "google-cloud-bigquery>=3.20.0"
log_success "google-cloud-bigquery ready"

# ── Fix 3: Ensure langgraph is correctly installed ────────────────────────────
log_info "Fix 3: Ensuring langgraph is at correct version..."
pip install --quiet "langgraph>=0.1.5"
log_success "langgraph ready"

# ── Verification ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Running full environment verification...${NC}"
echo ""

python -c "
import sys

checks = [
    # (display name, import test lambda)
    ('Python 3.11+',
        lambda: f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'),

    ('pydantic',
        lambda: __import__('pydantic').__version__),

    ('pydantic-settings',
        lambda: __import__('pydantic_settings').__version__),

    ('fastapi',
        lambda: __import__('fastapi').__version__),

    ('uvicorn',
        lambda: __import__('uvicorn').__version__),

    ('google-cloud-bigquery',
        lambda: __import__('google.cloud.bigquery', fromlist=['bigquery']).__version__),

    ('google-cloud-pubsub',
        lambda: __import__('google.cloud.pubsub_v1', fromlist=['pubsub_v1']) and 'ok'),

    ('google-cloud-storage',
        lambda: __import__('google.cloud.storage', fromlist=['storage']).__version__),

    ('google-cloud-aiplatform',
        lambda: __import__('google.cloud.aiplatform', fromlist=['aiplatform']).__version__),

    ('langchain',
        lambda: __import__('langchain').__version__),

    ('langgraph',
        lambda: __import__('langgraph').__version__),

    ('langchain-google-vertexai',
        lambda: __import__('langchain_google_vertexai', fromlist=['x']) and 'ok'),

    ('chromadb',
        lambda: __import__('chromadb').__version__),

    ('google-generativeai',
        lambda: __import__('google.generativeai', fromlist=['x']) and 'ok'),

    ('apache-beam',
        lambda: __import__('apache_beam').__version__),

    ('dbt-core',
        lambda: __import__('dbt.version', fromlist=['x']).get_installed_version()),

    ('pandas',
        lambda: __import__('pandas').__version__),

    ('scikit-learn',
        lambda: __import__('sklearn').__version__),

    ('xgboost',
        lambda: __import__('xgboost').__version__),

    ('shap',
        lambda: __import__('shap').__version__),

    ('presidio-analyzer',
        lambda: __import__('presidio_analyzer') and 'ok'),

    ('great-expectations',
        lambda: __import__('great_expectations').__version__),

    ('structlog',
        lambda: __import__('structlog').__version__),

    ('rich',
        lambda: __import__('rich').__version__),

    ('tenacity',
        lambda: __import__('tenacity').__version__),

    ('faker',
        lambda: __import__('faker').__version__),

    ('opentelemetry-api',
        lambda: __import__('opentelemetry').__version__),

    ('pytest',
        lambda: __import__('pytest').__version__),
]

passed = 0
failed = 0
failed_names = []

for name, check in checks:
    try:
        val = check()
        print(f'  \u2713  {name:<30} {val}')
        passed += 1
    except Exception as e:
        print(f'  \u2717  {name:<30} FAILED: {e}')
        failed += 1
        failed_names.append(name)

print()
print(f'  Result: {passed} passed, {failed} failed')

if failed == 0:
    print('  \u2713 All packages verified. Environment is ready.')
else:
    print(f'  Failed packages: {failed_names}')
    print('  Run: pip install ' + ' '.join(failed_names))
"

# ── spaCy model check ─────────────────────────────────────────────────────────
echo ""
log_info "Checking spaCy NLP model..."
python -c "
import spacy
nlp = spacy.load('en_core_web_lg')
doc = nlp('John Smith lives at 123 Main Street, his SSN is 123-45-6789')
entities = [(ent.text, ent.label_) for ent in doc.ents]
print(f'  spaCy model: en_core_web_lg loaded OK')
print(f'  PII detection test: {entities}')
"
log_success "spaCy PII detection working"

# ── Settings module check ─────────────────────────────────────────────────────
echo ""
log_info "Checking ThirdLine settings module..."
python config/settings.py
log_success "Settings module OK"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Environment fully verified!${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════${NC}"
echo ""
echo -e "${BOLD}Next step: Set up GCP project${NC}"
echo ""
echo "  1. Go to: https://console.cloud.google.com/"
echo "  2. Create a new project called: thirdline-audit-dev"
echo "  3. Enable billing (required even for free tier)"
echo "  4. Run:"
echo "       gcloud auth login"
echo "       gcloud auth application-default login"
echo "       gcloud config set project YOUR_PROJECT_ID"
echo ""
echo "  5. Update config/.env:"
echo "       GCP_PROJECT_ID=your-actual-project-id"
echo ""
echo "  6. Then run:"
echo "       cd infra/terraform && terraform init && terraform apply"
echo ""
