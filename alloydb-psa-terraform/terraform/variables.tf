variable "gcp_project_id" {
  description = "The GCP project ID."
  type        = string
}

variable "region" {
  description = "The GCP region for resources."
  type        = string
  default     = "us-central1"
}

variable "argolis" {
  description = "Whether to override Argolis policies."
  type        = bool
  default     = false
}

variable "alloydb_password" {
  description = "The password for the 'postgres' user in AlloyDB."
  type        = string
  sensitive   = true
}

variable "alloydb_cluster_id" {
  description = "The ID of the AlloyDB cluster."
  type        = string
  default     = "alloydb-psa-cluster"
}

variable "alloydb_instance_id" {
  description = "The ID of the AlloyDB primary instance."
  type        = string
  default     = "alloydb-psa-instance"
}

variable "alloydb_availability_type" {
  description = "Availability type for the AlloyDB instance. Choices are ZONAL or REGIONAL."
  type        = string
  default     = "ZONAL"
}
