# ThirdLine — Day 1 Step-by-Step Guide

> **Goal:** By end of Day 1, you have GCP infrastructure provisioned, all 5 synthetic
> agents running, telemetry flowing into BigQuery, and dbt models passing.

---

## Before You Start

Open your terminal. All commands run from the `thirdline/` project root unless noted.

Estimated time: 8–9 hours with breaks. Follow the blocks in order — each one
builds on the previous.

---

## Block 1: Project Setup (9:00 – 9:45)

### 1.1 Create and enter the project folder

```bash
# Go to wherever you keep your projects
cd ~/Projects    # or ~/Desktop, wherever you prefer

# The thirdline folder was already created when you unzipped the Day 1 package
cd thirdline

# Confirm you are in the right place
ls
# You should see: README.md  requirements.txt  scripts/  config/  agents_under_audit/  ...
```

### 1.2 Run the Mac setup script

```bash
# Make it executable
chmod +x scripts/mac_setup.sh

# Run it — this takes 3–5 minutes
./scripts/mac_setup.sh
```

The script will:
- Install Homebrew (if missing)
- Install Python 3.11, Node.js 20, Google Cloud SDK, Terraform
- Create a Python virtual environment at `./venv/`
- Install all 80+ Python packages
- Download the spaCy NLP model for PII detection
- Print a final checklist

**If it fails mid-way:** Read the error message. Most failures are network issues.
Run it again — it is idempotent (safe to re-run).

### 1.3 Activate the virtual environment

```bash
source venv/bin/activate
```

Your terminal prompt should now show `(venv)` at the start. You will need to
run this every time you open a new terminal.

```bash
# Confirm Python is from the venv, not system
which python
# Should show: /path/to/thirdline/venv/bin/python

python --version
# Should show: Python 3.11.x
```

### 1.4 Set up your environment file

```bash
# Copy the example config
cp config/.env.example config/.env

# Open it in your editor
open -e config/.env      # TextEdit
# OR
code config/.env         # VS Code (if installed)
# OR
nano config/.env         # Terminal editor
```

Minimum values to set right now (you can fill GCP values after Step 2):

```
APP_ENV=development
LOCAL_MODE=true
SYNTHETIC_INTERACTIONS_PER_AGENT=50
```

If you have a Gemini API key already (get one free at aistudio.google.com):
```
GEMINI_API_KEY=your-actual-key-here
LOCAL_MODE=false   # only if you want real LLM responses
```

**If you do NOT have a Gemini key yet:** leave `LOCAL_MODE=true`. The agents
will use mock responses for now. You can add the key later and re-run.

### 1.5 Verify settings load correctly

```bash
python config/settings.py
```

Expected output:
```json
{
  "APP_ENV": "development",
  "LOCAL_MODE": true,
  "GCP_PROJECT_ID": "your-gcp-project-id",
  ...
}
Settings loaded successfully.
```

---

## Block 2: GCP Setup + Terraform (9:45 – 11:00)

### 2.1 Create a GCP project

1. Go to: https://console.cloud.google.com/
2. Click the project selector dropdown (top left)
3. Click "New Project"
4. Name: `thirdline-audit-dev`
5. Copy the Project ID (it may look like `thirdline-audit-dev-123456`)
6. Click Create

### 2.2 Enable billing

GCP requires a billing account for most services even within free-tier limits.
- Go to: https://console.cloud.google.com/billing
- Link a billing account (a debit/credit card is required but won't be charged
  for free-tier usage)
- **Set a budget alert at $10** to avoid surprises:
  Billing → Budgets & Alerts → Create Budget → $10 threshold → Save

### 2.3 Authenticate gcloud CLI

```bash
# Login to Google account
gcloud auth login
# This opens a browser — sign in with your Google account

# Set application default credentials (used by Python SDKs)
gcloud auth application-default login

# Set your project
gcloud config set project YOUR_PROJECT_ID
# Replace YOUR_PROJECT_ID with your actual project ID from step 2.1

# Verify
gcloud config list
```

### 2.4 Update config/.env with GCP values

```bash
open -e config/.env
```

Update:
```
GCP_PROJECT_ID=your-actual-project-id
LOCAL_MODE=false   # Now GCP is ready
```

### 2.5 Provision infrastructure with Terraform

```bash
cd infra/terraform

# Initialise Terraform (downloads provider plugins)
terraform init
# Expected: "Terraform has been successfully initialized!"

# Preview what will be created (no changes yet)
terraform plan -var="project_id=YOUR_PROJECT_ID"
# Review the list — you should see ~15 resources

# Create the infrastructure
terraform apply -var="project_id=YOUR_PROJECT_ID"
# Type 'yes' when prompted
# Expected: "Apply complete! Resources: 15 added."
```

**Terraform creates:**
- 2 Cloud Storage buckets (raw telemetry + artifacts)
- 1 Pub/Sub topic + subscription + dead-letter queue
- 1 BigQuery dataset
- 2 service accounts + IAM bindings
- 1 Artifact Registry

```bash
# Go back to project root
cd ../..
```

### 2.6 Create BigQuery tables

```bash
# Run the DDL to create all 8 tables
bq query \
  --project_id=YOUR_PROJECT_ID \
  --use_legacy_sql=false \
  < data_engineering/schemas/bigquery_ddl.sql

# Verify tables were created
bq ls --project_id=YOUR_PROJECT_ID thirdline
```

Expected output:
```
        tableId          Type    Labels   Time Partitioning
 ─────────────────── ─────────  ──────  ──────────────────────────────────────
  audit_ledger         TABLE             DAY (field: event_ts)
  dim_agent            TABLE             DAY (field: first_seen_ts)
  dim_control          TABLE
  dim_model_version    TABLE             DAY (field: deployed_at)
  fact_agent_interaction TABLE           DAY (field: interaction_ts)
  fact_evaluation      TABLE             DAY (field: evaluated_at)
  fact_finding         TABLE             DAY (field: drafted_at)
  human_review_queue   TABLE             DAY (field: queued_at)
```

---

## Block 3: Synthetic Agent Fleet (11:00 – 12:30)

### 3.1 Test a single agent in LOCAL_MODE first

```bash
# Quick sanity check — run one agent manually
python -c "
from agents_under_audit.agents.agent_fleet import MortgageFAQAgent
agent = MortgageFAQAgent()
response = agent.respond(
    prompt='What is the minimum down payment for an FHA loan?',
    interaction_index=5  # Index 5 has hallucination injected
)
print('Output:', response.output_redacted[:200])
print('Is defect:', response.is_injected_defect)
print('Defect type:', response.injected_defect_type)
print('Latency (ms):', response.latency_ms)
"
```

Expected output (LOCAL_MODE):
```
Output: FHA loans offer accessible financing for first-time homebuyers...
        Note: Per updated FHA guidelines effective Q1 2024, all FHA loan
        applications now require a minimum credit score of 700 to qualify...
Is defect: True
Defect type: hallucination
Latency (ms): 3
```

The `Note: Per updated FHA guidelines...` is the injected hallucination. ✓

### 3.2 Run the full fleet (all 5 agents, 50 interactions each)

```bash
# Run with dry-run first to see the plan
python scripts/run_fleet.py --dry-run

# Run for real
python scripts/run_fleet.py
```

This takes 2–3 minutes in LOCAL_MODE, 5–10 minutes with real Gemini calls.

Watch the progress bars. Expected output:
```
┌─────────────────────────────────────────────────────┐
│ ThirdLine — Fleet Runner                             │
│ Generating synthetic agent interactions              │
└─────────────────────────────────────────────────────┘

╔═══════════════════════════════════════════════════╗
║ Run Plan                                          ║
╠══════════════════╦══════╦═════════════╦═══════════╣
║ Agent            ║ Tier ║ Interactions ║ Defect   ║
╠══════════════════╬══════╬═════════════╬═══════════╣
║ mortgage-faq     ║ HIGH ║ 50          ║ hallucin. ║
║ kyc-summary      ║ HIGH ║ 50          ║ reliabil. ║
║ lending-decision ║ HIGH ║ 50          ║ bias      ║
║ fx-posttrade     ║ MED  ║ 50          ║ drift     ║
║ compliance-qa    ║ HIGH ║ 50          ║ robustness║
╚══════════════════╩══════╩═════════════╩═══════════╝

✓ Fleet run complete!
  Total interactions: 250
  Total defects injected: 25
  Duration: 8.3s
  Next step: python scripts/run_audit.py
```

### 3.3 Verify output files

```bash
# Count interaction files
find data/interactions -name "*.json" | wc -l
# Expected: 250

# Look at one interaction
cat data/interactions/agt-mortgage-faq-001/$(ls data/interactions/agt-mortgage-faq-001/ | head -1) | python -m json.tool | head -40

# Check the run summary
cat data/interactions/run_summary.json | python -m json.tool
```

### 3.4 Load interactions into BigQuery

```bash
# Load all local JSON files into BigQuery
python -c "
import json
from pathlib import Path
from google.cloud import bigquery
from config.settings import settings

client = bigquery.Client(project=settings.GCP_PROJECT_ID)
table_id = settings.bq_table_interaction

rows = []
for filepath in Path('data/interactions').rglob('*.json'):
    if filepath.name == 'run_summary.json':
        continue
    data = json.loads(filepath.read_text())
    rows.append(data)

if rows:
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        print('BQ errors:', errors)
    else:
        print(f'Loaded {len(rows)} rows to BigQuery')
else:
    print('No rows found — check data/interactions/')
"
```

**If you are in LOCAL_MODE (no GCP):** skip this step. The evaluation pipeline
reads from local JSON files directly.

---

## Block 4: Dataflow Pipeline (Optional for MVP) (13:00 – 14:30)

> **MVP shortcut:** If you want to skip the Dataflow pipeline and run end-to-end
> faster, the evaluation pipeline reads from `data/interactions/` local JSON files.
> Come back to this block for the Advanced version. Mark it in your notes.

If you want to build it now:

```bash
# Test the pipeline locally with DirectRunner (no GCP needed)
python data_engineering/beam/pipeline.py \
  --runner=DirectRunner \
  --input_dir=data/interactions \
  --output_table=YOUR_PROJECT_ID:thirdline.fact_agent_interaction
```

---

## Block 5: dbt Setup (14:30 – 16:00)

### 5.1 Initialise dbt project

```bash
cd data_engineering/dbt

# Initialise dbt (creates profiles.yml template)
dbt init thirdline_dbt --skip-profile-setup

# Copy our pre-built models (already in the package)
# The dbt directory already has models/ from the Day 1 zip
```

### 5.2 Configure dbt profile

```bash
mkdir -p ~/.dbt
cat > ~/.dbt/profiles.yml << 'EOF'
thirdline:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: oauth
      project: YOUR_PROJECT_ID
      dataset: thirdline
      location: US
      threads: 4
      timeout_seconds: 300
EOF
```

Replace `YOUR_PROJECT_ID` with your actual project ID.

### 5.3 Test dbt connection

```bash
dbt debug
# Expected: "All checks passed!"
```

### 5.4 Run dbt models

```bash
dbt run
dbt test
```

---

## Block 6: End-of-Day Verification (16:00 – 17:00)

```bash
# Run the full Day 1 checklist
python -c "
from pathlib import Path
import json

checks = []

# Check 1: Virtual environment
import sys
checks.append(('Python from venv', 'venv' in sys.executable))

# Check 2: Interaction files exist
count = len(list(Path('data/interactions').rglob('*.json'))) - 1  # -1 for summary
checks.append((f'Interaction files ({count}/250)', count == 250))

# Check 3: Ground truth loaded
gt = json.loads(Path('agents_under_audit/data/ground_truth.json').read_text())
checks.append(('Ground truth file', len(gt['agents']) == 5))

# Check 4: Settings load
from config.settings import settings
checks.append(('Settings module', settings.APP_ENV == 'development'))

# Check 5: Run summary
summary_path = Path('data/interactions/run_summary.json')
checks.append(('Run summary exists', summary_path.exists()))

# Print results
print()
print('=== Day 1 Checklist ===')
all_pass = True
for label, result in checks:
    status = '✓' if result else '✗'
    print(f'  {status}  {label}')
    if not result:
        all_pass = False
print()
if all_pass:
    print('All Day 1 checks PASSED. Ready for Day 2!')
else:
    print('Some checks failed — review above.')
"
```

### Commit Day 1 work

```bash
git init     # if not already a git repo
git add .
git commit -m "Day 1: infrastructure + synthetic fleet + 250 interactions"
```

---

## Day 1 Fallbacks

**If Terraform fails (auth error):**
```bash
gcloud auth application-default login
# Then retry terraform apply
```

**If Terraform fails (API not enabled):**
```bash
gcloud services enable bigquery.googleapis.com pubsub.googleapis.com storage.googleapis.com
# Then retry
```

**If BigQuery table creation fails:**
```bash
# Run tables one at a time and check each
bq mk --table YOUR_PROJECT_ID:thirdline.dim_agent
```

**If fleet produces 0 interactions:**
```bash
# Check LOCAL_MODE and data dir
python -c "from config.settings import settings; print(settings.LOCAL_MODE, settings.data_dir)"
mkdir -p data/interactions
python scripts/run_fleet.py
```

**If pip install fails on apache-beam:**
```bash
pip install "apache-beam[gcp]" --no-build-isolation
```

---

## What You Built Today

| Component | Status | Location |
|-----------|--------|----------|
| GCP project + billing | ✓ | GCP Console |
| Terraform infra (buckets, Pub/Sub, BQ) | ✓ | infra/terraform/ |
| BigQuery 8-table schema | ✓ | data_engineering/schemas/ |
| 5 synthetic bank agents | ✓ | agents_under_audit/agents/ |
| 250 interactions with injected defects | ✓ | data/interactions/ |
| Ground truth labels | ✓ | agents_under_audit/data/ground_truth.json |
| Python venv + all packages | ✓ | venv/ |

## What's Next: Day 2

Day 2 builds the **agentic audit layer** — the orchestrator and 5 sub-agents
(Inventory, Evidence, Evaluation, Control-Mapping, Workpaper) that read from
`data/interactions/` and produce audit findings.

Start Day 2 with:
```bash
source venv/bin/activate
python scripts/run_audit.py --dry-run  # preview tomorrow's run
```
