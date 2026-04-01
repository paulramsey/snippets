output "vpc_name" {
  description = "The name of the created VPC."
  value       = google_compute_network.demo_vpc.name
}

output "alloydb_cluster_name" {
  description = "The name of the AlloyDB cluster."
  value       = google_alloydb_cluster.default.name
}

output "alloydb_private_ip" {
  description = "The Private IP address of the AlloyDB instance."
  value       = google_alloydb_instance.primary.ip_address
}

output "test_vm_name" {
  description = "The name of the Test VM."
  value       = google_compute_instance.test_vm.name
}

output "test_vm_zone" {
  description = "The zone of the Test VM."
  value       = google_compute_instance.test_vm.zone
}

output "alloydb_public_ip" {
  description = "The Public IP address of the AlloyDB instance."
  value       = google_alloydb_instance.primary.public_ip_address
}
