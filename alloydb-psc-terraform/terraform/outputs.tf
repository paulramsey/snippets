output "vpc_name" {
  description = "The name of the created VPC."
  value       = google_compute_network.demo_vpc.name
}

output "alloydb_cluster_name" {
  description = "The name of the AlloyDB cluster."
  value       = google_alloydb_cluster.default.name
}

output "alloydb_psc_endpoint_ip" {
  description = "The IP address of the PSC Endpoint for AlloyDB."
  value       = google_compute_address.psc_endpoint_ip.address
}

output "alloydb_service_attachment" {
  description = "The Service Attachment Link for AlloyDB."
  value       = google_alloydb_instance.primary.psc_instance_config[0].service_attachment_link
}

output "alloydb_psc_dns_name" {
  description = "The DNS name for the AlloyDB PSC instance."
  value       = google_alloydb_instance.primary.psc_instance_config[0].psc_dns_name
}

output "test_vm_name" {
  description = "The name of the Test VM."
  value       = google_compute_instance.test_vm.name
}

output "test_vm_zone" {
  description = "The zone of the Test VM."
  value       = google_compute_instance.test_vm.zone
}
output "alloydb_dns_zone_name" {
  description = "The DNS name of the Private Zone."
  value       = google_dns_managed_zone.alloydb_psc_zone.dns_name
}
output "alloydb_public_ip" {
  description = "The Public IP address of the AlloyDB instance."
  value       = google_alloydb_instance.primary.public_ip_address
}
