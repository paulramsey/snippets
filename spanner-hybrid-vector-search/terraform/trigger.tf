resource "google_eventarc_trigger" "gcs_trigger" {
  name     = "trigger-doc-upload"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }
  
  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.input_bucket.name
  }

  destination {
    cloud_run_service {
      service = google_cloudfunctions2_function.doc_processor.name
      region  = var.region
    }
  }

  service_account = google_service_account.function_sa.email

  depends_on = [
    google_project_service.services,
    google_cloudfunctions2_function.doc_processor
  ]
}
