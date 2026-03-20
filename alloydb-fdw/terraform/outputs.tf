# outputs.tf

output "cluster_a_psc_ip" {
  description = "The internal IP address for Cluster A PSC Endpoint."
  value       = google_compute_address.psc_endpoint_ip_a.address
}

output "cluster_a_service_attachment" {
  description = "The Service Attachment Link for Cluster A AlloyDB."
  value       = google_alloydb_instance.instance_a.psc_instance_config[0].service_attachment_link
}

output "cluster_a_psc_dns_name" {
  description = "The DNS name for the Cluster A AlloyDB PSC instance."
  value       = google_alloydb_instance.instance_a.psc_instance_config[0].psc_dns_name
}

output "cluster_a_public_ip" {
  description = "The Public IP address of the Cluster A AlloyDB instance."
  value       = google_alloydb_instance.instance_a.public_ip_address
}

# ==========================================
# Cluster B outputs
# ==========================================

output "cluster_b_psc_ip" {
  description = "The internal IP address for Cluster B PSC Endpoint."
  value       = google_compute_address.psc_endpoint_ip_b.address
}

output "cluster_b_service_attachment" {
  description = "The Service Attachment Link for Cluster B AlloyDB."
  value       = google_alloydb_instance.instance_b.psc_instance_config[0].service_attachment_link
}

output "cluster_b_psc_dns_name" {
  description = "The DNS name for the Cluster B AlloyDB PSC instance."
  value       = google_alloydb_instance.instance_b.psc_instance_config[0].psc_dns_name
}

output "cluster_b_public_ip" {
  description = "The Public IP address of the Cluster B AlloyDB instance."
  value       = google_alloydb_instance.instance_b.public_ip_address
}

# ==========================================
# Shared DNS Outputs
# ==========================================

output "alloydb_dns_zone_name" {
  description = "The DNS name of the Private Zone."
  value       = google_dns_managed_zone.alloydb_psc_zone.dns_name
}
