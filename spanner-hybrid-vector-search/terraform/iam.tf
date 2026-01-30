resource "google_service_account" "function_sa" {
  account_id   = "vector-search-fn-sa"
  display_name = "Vector Search Cloud Function Service Account"
}

# Roles for the Function Service Account
resource "google_project_iam_member" "sa_roles" {
  for_each = toset([
    "roles/spanner.databaseUser",
    "roles/aiplatform.user",
    "roles/storage.objectViewer",
    "roles/documentai.apiUser",
    "roles/logging.logWriter",
    "roles/eventarc.eventReceiver",
    "roles/run.invoker" # Required for 2nd Gen functions to be invoked by Eventarc
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.function_sa.email}"
}

# Grant Eventarc permission to invoke the function (Cloud Run)
resource "google_cloud_run_service_iam_member" "eventarc_invoker" {
  project    = var.project_id
  location   = var.region
  service    = google_cloudfunctions2_function.doc_processor.name
  role       = "roles/run.invoker"
  member     = "serviceAccount:${google_service_account.function_sa.email}"
  depends_on = [google_cloudfunctions2_function.doc_processor]
}

# Permissions for Cloud Build Service Account (required for function deployment)
# Usually <project_number>@cloudbuild.gserviceaccount.com
resource "google_project_iam_member" "cloudbuild_roles" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/artifactregistry.writer",
    "roles/storage.objectViewer"
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# Permissions for Default Compute Service Account (required by Cloud Build in some org configs)
resource "google_project_iam_member" "compute_sa_roles" {
  for_each = toset([
    "roles/cloudbuild.builds.builder"
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# Permissions for Eventarc Service Agent (P4SA)
# Required to validate bucket and set up pub/sub
resource "google_project_iam_member" "eventarc_sa_roles" {
  for_each = toset([
    "roles/eventarc.serviceAgent",
    "roles/storage.objectViewer"
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-eventarc.iam.gserviceaccount.com"
}

# Cloud Storage Service Agent Permission
# Validates that GCS can publish to Eventarc's Pub/Sub topic
data "google_storage_project_service_account" "gcs_account" {
}

resource "google_project_iam_member" "gcs_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}
