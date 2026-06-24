# =============================================================================
# ThirdLine — Terraform Infrastructure (GCP)
# =============================================================================
#
# FILE: infra/terraform/main.tf
#
# WHAT THIS FILE DOES:
#   Provisions all GCP infrastructure required for ThirdLine using
#   Infrastructure as Code (Terraform). Covers:
#     - GCP APIs enablement
#     - Cloud Storage buckets (raw telemetry + artifacts)
#     - Pub/Sub topic + subscription (telemetry streaming)
#     - BigQuery dataset (warehouse)
#     - Cloud Run service placeholder (API)
#     - Service accounts + IAM bindings
#
# HOW TO USE:
#   cd infra/terraform
#   terraform init
#   terraform plan -var="project_id=YOUR_PROJECT_ID"
#   terraform apply -var="project_id=YOUR_PROJECT_ID"
#
# COST ESTIMATE (GCP free tier covers most of this for dev):
#   - BigQuery: first 10GB storage + 1TB queries free/month
#   - Cloud Storage: first 5GB free/month
#   - Pub/Sub: first 10GB free/month
#   - Cloud Run: first 2M requests free/month
#
# INPUT:  var.project_id, var.region (with defaults)
# OUTPUT: All GCP resources created; outputs printed with resource IDs
# =============================================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# ── Provider ──────────────────────────────────────────────────────────────────
provider "google" {
  project = var.project_id
  region  = var.region
}

# ── Variables ─────────────────────────────────────────────────────────────────
variable "project_id" {
  description = "GCP project ID (override with: terraform apply -var='project_id=...')"
  type        = string
  default     = "thirdline-audit-dev"
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "us-central1"
}

variable "bq_dataset_location" {
  description = "BigQuery dataset location (US or EU)"
  type        = string
  default     = "US"
}

variable "environment" {
  description = "Environment tag: development | staging | production"
  type        = string
  default     = "development"
}

# ── Enable required GCP APIs ──────────────────────────────────────────────────
locals {
  required_apis = [
    "bigquery.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
    "dataflow.googleapis.com",
    "aiplatform.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)
  project  = var.project_id
  service  = each.value

  disable_dependent_services = false
  disable_on_destroy         = false
}

# ── Service Accounts ──────────────────────────────────────────────────────────

# ThirdLine application service account — used by Cloud Run and agents
resource "google_service_account" "thirdline_app" {
  account_id   = "thirdline-app"
  display_name = "ThirdLine Application Service Account"
  description  = "Used by Cloud Run API and agentic pipeline"
  project      = var.project_id

  depends_on = [google_project_service.apis]
}

# ThirdLine pipeline service account — used by Dataflow
resource "google_service_account" "thirdline_pipeline" {
  account_id   = "thirdline-pipeline"
  display_name = "ThirdLine Pipeline Service Account"
  description  = "Used by Dataflow / Apache Beam pipelines"
  project      = var.project_id

  depends_on = [google_project_service.apis]
}

# ── IAM Bindings ─────────────────────────────────────────────────────────────
# App service account permissions
resource "google_project_iam_member" "app_bigquery_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.thirdline_app.email}"
}

resource "google_project_iam_member" "app_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.thirdline_app.email}"
}

resource "google_project_iam_member" "app_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.thirdline_app.email}"
}

resource "google_project_iam_member" "app_storage_object_user" {
  project = var.project_id
  role    = "roles/storage.objectUser"
  member  = "serviceAccount:${google_service_account.thirdline_app.email}"
}

resource "google_project_iam_member" "app_vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.thirdline_app.email}"
}

# Pipeline service account permissions
resource "google_project_iam_member" "pipeline_dataflow_worker" {
  project = var.project_id
  role    = "roles/dataflow.worker"
  member  = "serviceAccount:${google_service_account.thirdline_pipeline.email}"
}

resource "google_project_iam_member" "pipeline_bigquery_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.thirdline_pipeline.email}"
}

resource "google_project_iam_member" "pipeline_pubsub_subscriber" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${google_service_account.thirdline_pipeline.email}"
}

resource "google_project_iam_member" "pipeline_storage_object_user" {
  project = var.project_id
  role    = "roles/storage.objectUser"
  member  = "serviceAccount:${google_service_account.thirdline_pipeline.email}"
}

# ── Cloud Storage Buckets ─────────────────────────────────────────────────────

# Raw telemetry landing — immutable, partitioned by date
resource "google_storage_bucket" "raw_telemetry" {
  name          = "${var.project_id}-thirdline-raw-telemetry"
  location      = var.region
  project       = var.project_id
  force_destroy = var.environment == "development"  # Only allow in dev

  # Versioning: keeps history so we can audit the pipeline itself
  versioning {
    enabled = true
  }

  # Lifecycle: move to cheaper storage after 90 days
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  # Lifecycle: delete raw files after 2 years (replace with BQ as source of truth)
  lifecycle_rule {
    condition {
      age = 730
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = var.environment
    project     = "thirdline"
    data_class  = "raw-telemetry"
  }

  depends_on = [google_project_service.apis]
}

# Artifacts bucket — pipeline outputs, workpapers, model cards
resource "google_storage_bucket" "artifacts" {
  name          = "${var.project_id}-thirdline-artifacts"
  location      = var.region
  project       = var.project_id
  force_destroy = var.environment == "development"

  versioning {
    enabled = true
  }

  labels = {
    environment = var.environment
    project     = "thirdline"
    data_class  = "artifacts"
  }

  depends_on = [google_project_service.apis]
}

# ── Pub/Sub ───────────────────────────────────────────────────────────────────

# Agent telemetry topic — agents publish OpenTelemetry spans here
resource "google_pubsub_topic" "agent_telemetry" {
  name    = "thirdline-agent-telemetry"
  project = var.project_id

  # Retain messages for 7 days (in case Dataflow falls behind)
  message_retention_duration = "604800s"

  labels = {
    environment = var.environment
    project     = "thirdline"
  }

  depends_on = [google_project_service.apis]
}

# Telemetry subscription — Dataflow reads from this
resource "google_pubsub_subscription" "agent_telemetry_sub" {
  name    = "thirdline-agent-telemetry-sub"
  topic   = google_pubsub_topic.agent_telemetry.name
  project = var.project_id

  # Messages held for 7 days if not acked (same as topic retention)
  message_retention_duration = "604800s"
  retain_acked_messages      = false

  # Acknowledgement deadline — Dataflow needs longer for complex processing
  ack_deadline_seconds = 300  # 5 minutes

  # Dead-letter topic for failed messages
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.agent_telemetry_dlq.id
    max_delivery_attempts = 5
  }

  labels = {
    environment = var.environment
    project     = "thirdline"
  }
}

# Dead-letter queue — failed telemetry messages land here for investigation
resource "google_pubsub_topic" "agent_telemetry_dlq" {
  name    = "thirdline-agent-telemetry-dlq"
  project = var.project_id

  labels = {
    environment = var.environment
    project     = "thirdline"
  }

  depends_on = [google_project_service.apis]
}

# ── BigQuery ──────────────────────────────────────────────────────────────────

# ThirdLine dataset
resource "google_bigquery_dataset" "thirdline" {
  dataset_id  = "thirdline"
  location    = var.bq_dataset_location
  project     = var.project_id
  description = "ThirdLine — AI Audit & Governance Platform data warehouse"

  # Delete protection (don't allow accidental dataset deletion with data)
  delete_contents_on_destroy = var.environment == "development"

  labels = {
    environment = var.environment
    project     = "thirdline"
  }

  depends_on = [google_project_service.apis]
}

# Artifact Registry — Docker images for Cloud Run
resource "google_artifact_registry_repository" "thirdline" {
  location      = var.region
  repository_id = "thirdline"
  format        = "DOCKER"
  project       = var.project_id
  description   = "ThirdLine Docker images"

  labels = {
    environment = var.environment
    project     = "thirdline"
  }

  depends_on = [google_project_service.apis]
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "project_id" {
  value       = var.project_id
  description = "GCP project ID"
}

output "raw_telemetry_bucket" {
  value       = google_storage_bucket.raw_telemetry.name
  description = "Cloud Storage bucket for raw telemetry"
}

output "artifacts_bucket" {
  value       = google_storage_bucket.artifacts.name
  description = "Cloud Storage bucket for artifacts and workpapers"
}

output "pubsub_topic" {
  value       = google_pubsub_topic.agent_telemetry.id
  description = "Pub/Sub topic for agent telemetry"
}

output "pubsub_subscription" {
  value       = google_pubsub_subscription.agent_telemetry_sub.id
  description = "Pub/Sub subscription for Dataflow"
}

output "bigquery_dataset" {
  value       = google_bigquery_dataset.thirdline.dataset_id
  description = "BigQuery dataset ID"
}

output "app_service_account_email" {
  value       = google_service_account.thirdline_app.email
  description = "App service account — use in Cloud Run deployment"
}

output "artifact_registry_url" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/thirdline"
  description = "Docker image registry URL"
}

output "next_steps" {
  value = <<-EOT
    ════════════════════════════════════════════
    Infrastructure provisioned. Next steps:
    ════════════════════════════════════════════

    1. Create BigQuery tables:
       bq query --use_legacy_sql=false < ../../data_engineering/schemas/bigquery_ddl.sql

    2. Update config/.env:
       GCP_PROJECT_ID=${var.project_id}
       GCS_BUCKET_RAW=${google_storage_bucket.raw_telemetry.name}
       GCS_BUCKET_ARTIFACTS=${google_storage_bucket.artifacts.name}

    3. Run the synthetic fleet:
       cd ../..
       source venv/bin/activate
       python scripts/run_fleet.py
  EOT
  description = "Next steps after terraform apply"
}
