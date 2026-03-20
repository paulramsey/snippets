variable "gcp_project_id" {
  type        = string
  description = "The Google Cloud Project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "The Google Cloud Region"
}

variable "alloydb_password" {
  type        = string
  default     = "SuperSecretPassword@123"
  description = "The initial password for the AlloyDB postgres user."
}

variable "argolis" {
  type        = bool
  default     = false
  description = "Set to true to override Argolis org policies"
}
