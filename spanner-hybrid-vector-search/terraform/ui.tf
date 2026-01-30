variable "ui_image_name" {
  description = "Name of the UI container image"
  type        = string
  default     = "spanner-search-ui"
}

resource "google_artifact_registry_repository" "ui_repo" {
  location      = var.region
  repository_id = "ui-repo"
  description   = "Docker repository for Spanner Search UI"
  format        = "DOCKER"

  depends_on = [google_project_service.services]
}

# We use a null_resource to build the image because Terraform doesn't natively build Docker images.
# This requires gcloud and docker to be installed on the machine running Terraform.
resource "null_resource" "build_and_push_ui" {
  triggers = {
    # Rebuild if any file in src/ui changes
    dir_sha1 = sha1(join("", [for f in fileset("${path.module}/../src/ui", "**") : filesha1("${path.module}/../src/ui/${f}")]))
  }

  provisioner "local-exec" {
    command = <<EOT
      gcloud builds submit ${path.module}/../src/ui \
        --tag ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ui_repo.name}/${var.ui_image_name}:latest \
        --project ${var.project_id}
    EOT
  }
}

resource "google_cloud_run_v2_service" "ui_service" {
  name     = "spanner-search-ui"
  location = var.region
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ui_repo.name}/${var.ui_image_name}:latest"
      
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "SPANNER_INSTANCE"
        value = google_spanner_instance.vector_db.name
      }
      env {
        name  = "SPANNER_DATABASE"
        value = google_spanner_database.embeddings_db.name
      }
      
      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    null_resource.build_and_push_ui,
    google_project_service.services
  ]
}

# Allow unauthenticated access for demo purposes
resource "google_cloud_run_service_iam_member" "ui_public_access" {
  location = google_cloud_run_v2_service.ui_service.location
  service  = google_cloud_run_v2_service.ui_service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "ui_url" {
  value = google_cloud_run_v2_service.ui_service.uri
}
