# AlloyDB with PSC, AI, and Columnar Engine (Terraform)

This snippet contains Terraform code to deploy a fully configured **Google Cloud AlloyDB** environment with advanced features enabled, including **AlloyDB AI**, **Columnar Engine**, and **Parameterized Secure Views**.

It also sets up a complete network infrastructure using **Private Service Connect (PSC)**, a Test VM, and Private DNS.

## Features Deployed

*   **AlloyDB Cluster & Instance**:
    *   **AlloyDB AI**: Enabled (`google_ml_integration.enable_model_support`, `alloydb_ai_nl.enabled`).
    *   **Columnar Engine**: Enabled (`google_columnar_engine.enabled`) for analytical performance.
    *   **Parameterized Secure Views**: Enabled (`parameterized_views.enabled`).
    *   **High Availability**: Configured (Zonal/Regional as defined in `variables.tf`).
*   **Networking**:
    *   **VPC**: A dedicated VPC (`demo-vpc`) for the environment.
    *   **Private Service Connect (PSC)**: Secure private connectivity without global peering.
    *   **Public IP**: Optional public access restricted to your IP address.
    *   **Private DNS**: Managed Zone and Record Set for resolving the AlloyDB instance name.
*   **Testing**:
    *   **Test VM**: A Compute Engine instance (`test-vm`) compliant with Shielded VM policies, pre-loaded with `postgresql-client` for connectivity testing.

## Prerequisites

Before deploying, ensure you have the following:

1.  **Google Cloud Project**:
    *   Create a NEW project (recommended to avoid conflicts).
    *   Enable **Billing** for the project.
    
    ```bash
    # Create project
    gcloud projects create YOUR_PROJECT_ID
    
    # Link billing (Find your BILLING_ACCOUNT_ID with `gcloud billing accounts list`)
    gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
    ```

2.  **Tools Installed**:
    *   [Terraform](https://developer.hashicorp.com/terraform/install) (>= 1.0)
    *   [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) (`gcloud`)

3.  **Authentication**:
    *   Login to `gcloud` and set your application default credentials.
    
    ```bash
    gcloud auth login
    gcloud auth application-default login
    ```

## Deployment Steps

1.  **Navigate to the Terraform directory**:
    ```bash
    cd terraform
    ```

2.  **Initialize Terraform**:
    ```bash
    terraform init
    ```

3.  **Configure Variables**:
    *   Update `terraform.tfvars` with your Project ID and Region.
    *   **Important**: Update `alloydb_password` with a strong password.
    *   **Important**: Set `argolis` to `true` if deploying to an Argolis environment. This will handle necessary org policies for you.
    
    ```hcl
    # terraform.tfvars
    gcp_project_id   = "YOUR_PROJECT_ID"
    region           = "us-central1"
    alloydb_password        = "StrongPassword!"
    alloydb_availability_type = "ZONAL" # or REGIONAL
    # ... other variables
    ```

4.  **Review the Plan**:
    ```bash
    terraform plan
    ```

5.  **Apply the Configuration**:
    ```bash
    terraform apply
    ```
    *   Type `yes` when prompted.
    *   Deployment typically takes 15-20 minutes (AlloyDB cluster creation).

## Connecting to AlloyDB

After deployment, Terraform will output connectivity details.

### Option 1: From the Test VM (Private)
1.  **SSH into the Test VM**:
    ```bash
    gcloud compute ssh $(terraform output -raw test_vm_name) --zone $(terraform output -raw test_vm_zone)
    ```
2.  **Connect using Private DNS**:
    ```bash
    # The DNS name corresponds to the PSC Endpoint in your VPC
    psql "host=$(terraform output -raw alloydb_psc_dns_name) user=postgres sslmode=require"
    ```

### Option 2: From your Local Machine (Public)
1.  **Get the Public IP**:
    ```bash
    terraform output alloydb_public_ip
    ```
2.  **Connect**:
    ```bash
    export DB_HOST=$(terraform output -raw alloydb_public_ip)
    psql "host=$DB_HOST user=postgres sslmode=require"
    ```
    *(Note: Access is automatically restricted to the IP address from which you ran `terraform apply`.)*

## Clean Up

When you are finished with the environment, **delete the project** to ensure all resources are destroyed and you stop incurring charges.

```bash
gcloud projects delete YOUR_PROJECT_ID
```

Alternatively, you can run `terraform destroy`, but deleting the project is the safest way to ensure nothing is left behind associated with the environment.
