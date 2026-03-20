terraform {
  required_providers {
    google = {
      source  = "hashicorp/google-beta"
      version = ">= 5.35.0"
    }
    null = {
      source  = "hashicorp/null"
      version = ">= 3.1"
    }
    http = {
      source  = "hashicorp/http"
      version = ">= 3.4"
    }
  }
}

# Configure the Google Cloud provider
provider "google" {
  project = var.gcp_project_id
  region  = var.region
}


# Get execution environment IP for network security rules
data "http" "myip" {
  url = "https://ipv4.icanhazip.com"
}

# Access the project data object
data "google_project" "project" {
  project_id = var.gcp_project_id
}

# Get authentication token for the local-exec provisioner
data "google_client_config" "current" {}

# Set gcloud project scope
resource "null_resource" "gcloud_setup" {
  provisioner "local-exec" {
    command = <<-EOT
      gcloud config set project ${var.gcp_project_id}
      gcloud auth application-default set-quota-project ${var.gcp_project_id}
      gcloud auth configure-docker ${var.region}-docker.pkg.dev --quiet
    EOT
  }
}

# Enable the required Google Cloud APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "alloydb.googleapis.com",
    "logging.googleapis.com",
    "storage-component.googleapis.com",
    "serviceusage.googleapis.com",
    "networkmanagement.googleapis.com",
    "servicenetworking.googleapis.com",
    "dns.googleapis.com",
    "vpcaccess.googleapis.com",
    "iam.googleapis.com",
    "compute.googleapis.com",
    "networkconnectivity.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com"
  ])
  service                    = each.key
  disable_dependent_services = true
}

# Override the Argolis policies
resource "null_resource" "override_argolis_policies" {
  count      = var.argolis ? 1 : 0
  depends_on = [google_project_service.apis]

  provisioner "local-exec" {
    command = <<-EOT
      # Update org policies
      echo "Updating org policies"
      declare -a policies=("constraints/run.allowedIngress"
        "constraints/iam.allowedPolicyMemberDomains"
        "constraints/compute.vmExternalIpAccess"
      )
      for policy in "$${policies[@]}"; do
        cat <<EOF >new_policy.yaml
      constraint: $policy
      listPolicy:
        allValues: ALLOW
      EOF
        gcloud resource-manager org-policies set-policy new_policy.yaml --project="${var.gcp_project_id}"
      done

      rm new_policy.yaml

      # Wait for policies to apply
      echo "Waiting 90 seconds for Org policies to apply..."
      sleep 90
    EOT
  }
}

# Create a custom VPC
resource "google_compute_network" "demo_vpc" {
  name                    = "fdw-demo-vpc"
  auto_create_subnetworks = true
  mtu                     = 1460
  routing_mode            = "REGIONAL"
  depends_on              = [google_project_service.apis]
}

# Create a Cloud Router
resource "google_compute_router" "router" {
  name    = "nat-router"
  network = google_compute_network.demo_vpc.id
  region  = var.region
}

# Create a Cloud NAT Gateway
resource "google_compute_router_nat" "nat" {
  name                               = "managed-nat-gateway"
  router                             = google_compute_router.router.name
  region                             = google_compute_router.router.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Create firewall rule for IAP internal traffic
resource "google_compute_firewall" "iap_internal_communication" {
  name    = "allow-iap-internal"
  network = google_compute_network.demo_vpc.name
  project = var.gcp_project_id

  allow {
    protocol = "all"
  }

  source_ranges = ["35.235.240.0/20"]
  direction     = "INGRESS"
  priority      = 1000
  description   = "Allows internal TCP communication for IAP."
}

# Network Attachment for PSC
resource "google_compute_network_attachment" "default" {
  name                  = "alloydb-network-attachment"
  region                = var.region
  connection_preference = "ACCEPT_AUTOMATIC"
  subnetworks = [
    "projects/${var.gcp_project_id}/regions/${var.region}/subnetworks/fdw-demo-vpc"
  ]
  depends_on = [
    google_project_service.apis,
    google_compute_network.demo_vpc
  ]
}

# --- START: Section for creating the AlloyDB password secret ---
resource "google_secret_manager_secret" "alloydb_password" {
  depends_on = [google_project_service.apis]
  secret_id  = "alloydb-password"
  project    = var.gcp_project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "alloydb_password_version" {
  secret      = google_secret_manager_secret.alloydb_password.id
  secret_data = var.alloydb_password
}

locals {
  compute_service_account = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_secret_manager_secret_iam_member" "compute_sa_secret_accessor" {
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.alloydb_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.compute_service_account
}
# --- END: Section for creating the AlloyDB password secret ---


# --- START: Section for assigning permissions to the AlloyDB service account ---
locals {
  alloydb_sa_project_roles = [
    "roles/aiplatform.user",
    "roles/alloydb.serviceAgent",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/storage.admin",
    "roles/servicenetworking.serviceAgent"
  ]
  alloydb_service_account_member = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-alloydb.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "project_alloydb_sa_roles" {
  depends_on = [google_alloydb_cluster.cluster_a, google_alloydb_cluster.cluster_b]
  for_each   = toset(local.alloydb_sa_project_roles)
  project    = data.google_project.project.id
  role       = each.key
  member     = local.alloydb_service_account_member
}
# --- END: Section for assigning permissions to the AlloyDB service account ---

# ==========================================
# CLUSTER A SETUP (Local Databases for FDW)
# ==========================================

resource "google_alloydb_cluster" "cluster_a" {
  cluster_id          = "alloydb-cluster-a"
  location            = var.region
  deletion_policy     = "force"
  deletion_protection = false
  project             = var.gcp_project_id
  initial_user {
    password = var.alloydb_password
  }

  psc_config {
    psc_enabled = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_alloydb_instance" "instance_a" {
  depends_on = [
    null_resource.override_argolis_policies,
    google_project_service.apis
  ]

  cluster       = google_alloydb_cluster.cluster_a.name
  instance_id   = "alloydb-instance-a"
  instance_type = "PRIMARY"

  machine_config {
    cpu_count = 2
  }

  database_flags = {
    "password.enforce_complexity"    = "on"
    "password.min_uppercase_letters" = "1"
    "password.min_numerical_chars"   = "1"
    "password.min_pass_length"       = "10"
    "alloydb.enable_pg_cron"         = "on"
    "cron.database_name"             = "db_local"
  }

  client_connection_config {
    ssl_config {
      ssl_mode = "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    }
  }

  psc_instance_config {
    allowed_consumer_projects = [data.google_project.project.number]
    psc_interface_configs {
      network_attachment_resource = google_compute_network_attachment.default.id
    }
  }

  network_config {
    enable_public_ip = true
    authorized_external_networks {
      cidr_range = "${chomp(data.http.myip.response_body)}/32"
    }
  }
}

# Internal IP for the PSC Endpoint linking to Cluster A
resource "google_compute_address" "psc_endpoint_ip_a" {
  name         = "alloydb-psc-endpoint-a"
  region       = var.region
  subnetwork   = "projects/${var.gcp_project_id}/regions/${var.region}/subnetworks/fdw-demo-vpc"
  address_type = "INTERNAL"
  depends_on   = [google_project_service.apis, google_compute_network.demo_vpc]
}

# The PSC Forwarding Rule (Endpoint) covering Cluster A
resource "google_compute_forwarding_rule" "psc_endpoint_a" {
  name                  = "alloydb-psc-endpoint-a"
  region                = var.region
  network               = google_compute_network.demo_vpc.id
  ip_address            = google_compute_address.psc_endpoint_ip_a.id
  target                = google_alloydb_instance.instance_a.psc_instance_config[0].service_attachment_link
  load_balancing_scheme = "" # Must be empty for PSC
}


# ==========================================
# CLUSTER B SETUP (Remote Database for FDW)
# ==========================================

resource "google_alloydb_cluster" "cluster_b" {
  cluster_id          = "alloydb-cluster-b"
  location            = var.region
  deletion_policy     = "force"
  deletion_protection = false
  project             = var.gcp_project_id
  initial_user {
    password = var.alloydb_password
  }

  psc_config {
    psc_enabled = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_alloydb_instance" "instance_b" {
  depends_on = [
    null_resource.override_argolis_policies,
    google_project_service.apis
  ]

  cluster       = google_alloydb_cluster.cluster_b.name
  instance_id   = "alloydb-instance-b"
  instance_type = "PRIMARY"

  machine_config {
    cpu_count = 2
  }

  database_flags = {
    "password.enforce_complexity"    = "on"
    "password.min_uppercase_letters" = "1"
    "password.min_numerical_chars"   = "1"
    "password.min_pass_length"       = "10"
    "alloydb.enable_pg_cron"         = "on"
  }

  client_connection_config {
    ssl_config {
      ssl_mode = "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    }
  }

  psc_instance_config {
    allowed_consumer_projects = [data.google_project.project.number]
    psc_interface_configs {
      network_attachment_resource = google_compute_network_attachment.default.id
    }
  }

  network_config {
    enable_public_ip = true
    authorized_external_networks {
      cidr_range = "${chomp(data.http.myip.response_body)}/32"
    }
  }
}

# Internal IP for the PSC Endpoint linking to Cluster B
resource "google_compute_address" "psc_endpoint_ip_b" {
  name         = "alloydb-psc-endpoint-b"
  region       = var.region
  subnetwork   = "projects/${var.gcp_project_id}/regions/${var.region}/subnetworks/fdw-demo-vpc"
  address_type = "INTERNAL"
  depends_on   = [google_project_service.apis, google_compute_network.demo_vpc]
}

# The PSC Forwarding Rule (Endpoint) covering Cluster B
resource "google_compute_forwarding_rule" "psc_endpoint_b" {
  name                  = "alloydb-psc-endpoint-b"
  region                = var.region
  network               = google_compute_network.demo_vpc.id
  ip_address            = google_compute_address.psc_endpoint_ip_b.id
  target                = google_alloydb_instance.instance_b.psc_instance_config[0].service_attachment_link
  load_balancing_scheme = "" # Must be empty for PSC
}

# ==========================================
# DNS Setup for PSC Endpoint Mapping
# ==========================================

# Create a DNS private zone for AlloyDB PSC connectivity
resource "google_dns_managed_zone" "alloydb_psc_zone" {
  project     = var.gcp_project_id
  name        = "${var.region}-alloydb-psc-goog"
  dns_name    = "${var.region}.alloydb-psc.goog."
  description = "Private zone for AlloyDB PSC created by Terraform"

  visibility = "private"
  private_visibility_config {
    networks {
      network_url = google_compute_network.demo_vpc.id
    }
  }
}

# Create an 'A' record to map Cluster A's instance DNS name to the PSC endpoint IP.
resource "google_dns_record_set" "alloydb_psc_record_a" {
  project      = var.gcp_project_id
  type         = "A"
  rrdatas      = [google_compute_address.psc_endpoint_ip_a.address]
  name         = google_alloydb_instance.instance_a.psc_instance_config[0].psc_dns_name
  managed_zone = google_dns_managed_zone.alloydb_psc_zone.name
  ttl          = 300
}

# Create an 'A' record to map Cluster B's instance DNS name to the PSC endpoint IP.
resource "google_dns_record_set" "alloydb_psc_record_b" {
  project      = var.gcp_project_id
  type         = "A"
  rrdatas      = [google_compute_address.psc_endpoint_ip_b.address]
  name         = google_alloydb_instance.instance_b.psc_instance_config[0].psc_dns_name
  managed_zone = google_dns_managed_zone.alloydb_psc_zone.name
  ttl          = 300
}


