output "input_bucket_name" {
  value = google_storage_bucket.input_bucket.name
}

output "spanner_instance" {
  value = google_spanner_instance.vector_db.name
}

output "spanner_database" {
  value = google_spanner_database.embeddings_db.name
}

output "function_name" {
  value = google_cloudfunctions2_function.doc_processor.name
}

output "docai_ocr_processor_id" {
  value = google_document_ai_processor.ocr_parser.name
}

