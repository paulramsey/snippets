resource "google_document_ai_processor" "ocr_parser" {
  location     = "us"
  display_name = "ocr-processor"
  type         = "OCR_PROCESSOR"

  depends_on = [google_project_service.services]
}


