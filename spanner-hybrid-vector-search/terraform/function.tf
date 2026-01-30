data "archive_file" "function_source" {
  type        = "zip"
  source_dir  = "${path.module}/../src/cloud-run"
  output_path = "${path.module}/function-source.zip"
}

resource "google_storage_bucket_object" "function_archive" {
  name   = "source-${data.archive_file.function_source.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.function_source.output_path
}

resource "google_cloudfunctions2_function" "doc_processor" {
  name        = "doc-processor"
  location    = var.region
  description = "Processes uploaded documents and writes embeddings to Spanner"

  build_config {
    runtime     = "python314"
    entry_point = "process_document_event" # Will be defined in main.py
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.function_archive.name
      }
    }
  }

  service_config {
    max_instance_count    = 10
    available_memory      = "1Gi"
    timeout_seconds       = 300
    service_account_email = google_service_account.function_sa.email
    environment_variables = {
      PROJECT_ID             = var.project_id
      LOCATION               = var.region
      DOCAI_LOCATION         = "us"
      SPANNER_INSTANCE       = google_spanner_instance.vector_db.name
      SPANNER_DATABASE       = google_spanner_database.embeddings_db.name
      DOCAI_OCR_PROCESSOR_ID = google_document_ai_processor.ocr_parser.name
    }
  }

  depends_on = [
    google_project_service.services,
    google_project_iam_member.sa_roles
  ]
}
