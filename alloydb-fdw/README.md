# AlloyDB Cross-Database Join POC (FDW)

This repository contains a Proof of Concept (POC) demonstrating how to use `postgres_fdw` (Foreign Data Wrapper) to perform cross-database joins in AlloyDB for PostgreSQL. 

The POC covers two scenarios:
1.  **Intra-Cluster**: Joining data between separate databases within the *same* AlloyDB cluster. 
2.  **Inter-Cluster**: Joining data between databases in *different* AlloyDB clusters.

The setup utilizes **Private Service Connect (PSC)** for internal connectivity between the databases while exposing **Public IPs** (restricted to your local machine) for easy setup and querying via `psql`.

## Prerequisites
- Terraform >= 1.0
- Google Cloud CLI (`gcloud`)
- Local `psql` client

## Environment Variables

```bash
export PROJECT_ID=<your-project-id>
export REGION="us-central1"
export PASSWORD="SuperSecretPassword@123"
```

## Authenticate

```bash
# Authenticate with gcloud (interactive)
gcloud auth login

# Configure Application Default Credentials (ADC)
gcloud auth application-default login

# Set default project in gcloud config
gcloud config set project $PROJECT_ID

# Set the quota project for ADC
gcloud auth application-default set-quota-project $PROJECT_ID
```

## Deploying the Infrastructure with Terraform

The infrastructure is managed via Terraform and will provision a custom VPC, NAT, network attachments, and two AlloyDB clusters with PSC networks. The primary instances will be exposed via Public IPs that are securely restricted to your current local IP address by default.

```bash
cd terraform

# Initialize Terraform
terraform init

# Apply the configuration
terraform apply \
  -var="gcp_project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="alloydb_password=${PASSWORD}"
```

*Note: The script automatically queries `https://ipv4.icanhazip.com` to lock down the database public IP to your local connection environment.*

---

## Running the FDW Test

Retrieve the Public IPs and PSC IPs from the Terraform output.

```bash
# Export IPs from Terraform Outputs
export CLUSTER_A_PUBLIC_IP=$(terraform output -raw cluster_a_public_ip)
export CLUSTER_B_PUBLIC_IP=$(terraform output -raw cluster_b_public_ip)
export CLUSTER_A_PSC_IP=$(terraform output -raw cluster_a_psc_ip)
export CLUSTER_B_PSC_IP=$(terraform output -raw cluster_b_psc_ip)

echo "Cluster A Public IP: ${CLUSTER_A_PUBLIC_IP}"
echo "Cluster B Public IP: ${CLUSTER_B_PUBLIC_IP}"
```

### 1. Connect to Cluster A (Local and Staging Databases)

Use `psql` to connect to **Cluster A** using its Public IP.

```bash
PGPASSWORD=${PASSWORD} psql -h ${CLUSTER_A_PUBLIC_IP} -U postgres postgres
```

Run the following SQL to create databases:

```sql
CREATE DATABASE db_local;
CREATE DATABASE db_local_2;
```

### 2. Connect to Cluster B (Remote Cluster)

Use `psql` to connect to **Cluster B** using its Public IP.

```bash
PGPASSWORD=${PASSWORD} psql -h ${CLUSTER_B_PUBLIC_IP} -U postgres postgres
```

Run the following SQL to create the remote database:

```sql
CREATE DATABASE db_remote;
```

---

## Scenario 1: Intra-Cluster FDW

In this scenario, we connect **`db_local`** to **`db_local_2`** inside the **same cluster (Cluster A)**.
We will use the **PSC Endpoint IP of Cluster A** for the connection.

### 1. Setup Remote Data in `db_local_2`

Connect to `db_local_2` in Cluster A (from a new terminal tab):
```bash
PGPASSWORD=${PASSWORD} psql -h ${CLUSTER_A_PUBLIC_IP} -U postgres db_local_2
```

Create and populate the table:
```sql
CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    department_id INT
);

INSERT INTO employees (name, department_id) VALUES
('Alice', 1), ('Bob', 2), ('Charlie', 1), ('David', 3);
```

### 2. Setup FDW and Caching in `db_local`

Connect to `db_local` in Cluster A:
```bash
PGPASSWORD=${PASSWORD} psql -h ${CLUSTER_A_PUBLIC_IP} -U postgres db_local
```

Run the Setup SQL (Replace `CLUSTER_A_PSC_IP_HERE` and `YOUR_PASSWORD_HERE` below with the actual values. E.g.: `echo $CLUSTER_A_PSC_IP`):

```sql
-- 1. Enable the extension
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- 2. Define the remote server (Using Cluster A's PSC Endpoint)
CREATE SERVER local_remote_server
FOREIGN DATA WRAPPER postgres_fdw
OPTIONS (host 'CLUSTER_A_PSC_IP_HERE', dbname 'db_local_2', port '5432');

-- 3. Map local user to remote user
CREATE USER MAPPING FOR postgres
SERVER local_remote_server
OPTIONS (user 'postgres', password 'YOUR_PASSWORD_HERE');

-- 4. Import Schema
CREATE SCHEMA employees_remote_schema;
IMPORT FOREIGN SCHEMA public FROM SERVER local_remote_server INTO employees_remote_schema;

-- 5. Create Materialized View
CREATE MATERIALIZED VIEW local_employees AS
SELECT * FROM employees_remote_schema.employees;

-- Enables updating the materialized view concurrently
CREATE UNIQUE INDEX idx_employees_id ON local_employees(id);
```

---

## Scenario 2: Inter-Cluster FDW

In this scenario, we connect **`db_local`** (in Cluster A) to **`db_remote`** (in Cluster B).
We will use the **PSC Endpoint IP of Cluster B** for the connection.

### 1. Setup Remote Data in `db_remote`

Connect to `db_remote` in **Cluster B**:
```bash
PGPASSWORD=${PASSWORD} psql -h ${CLUSTER_B_PUBLIC_IP} -U postgres db_remote
```

Create and populate the table:
```sql
CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    dept_name TEXT NOT NULL
);

INSERT INTO departments (dept_name) VALUES
('Engineering'), ('Marketing'), ('Finance');
```

### 2. Setup FDW and Caching in `db_local`

Connect back to `db_local` in **Cluster A**:
```bash
PGPASSWORD=${PASSWORD} psql -h ${CLUSTER_A_PUBLIC_IP} -U postgres db_local
```

Run the Setup SQL (Replace `CLUSTER_B_PSC_IP_HERE` and `YOUR_PASSWORD_HERE`):

```sql
-- 1. Define the remote server (Using Cluster B's PSC Endpoint)
CREATE SERVER inter_cluster_server
FOREIGN DATA WRAPPER postgres_fdw
OPTIONS (host 'CLUSTER_B_PSC_IP_HERE', dbname 'db_remote', port '5432');

-- 2. Map local user to remote user
CREATE USER MAPPING FOR postgres
SERVER inter_cluster_server
OPTIONS (user 'postgres', password 'YOUR_PASSWORD_HERE');

-- 3. Import Schema
CREATE SCHEMA inter_cluster_schema;
IMPORT FOREIGN SCHEMA public FROM SERVER inter_cluster_server INTO inter_cluster_schema;

-- 4. Create Materialized View
CREATE MATERIALIZED VIEW inter_cluster_departments AS
SELECT * FROM inter_cluster_schema.departments;

CREATE UNIQUE INDEX idx_departments_id ON inter_cluster_departments(id);
```

---

## Verification & Automation

Connect to `db_local` in **Cluster A** (if not already):
```bash
PGPASSWORD=${PASSWORD} psql -h ${CLUSTER_A_PUBLIC_IP} -U postgres db_local
```

### 1. Run Cross-Database/Cross-Cluster Join

Perform a join using the cached Materialized Views from both scenarios. 

This single query explicitly validates both of our initial FDW goals simultaneously:
1. **`local_employees e`**: Pulls data from your Materialized View linked via FDW to `db_local_2` **(Local-Instance / Intra-Cluster FDW)**.
2. **`inter_cluster_departments d`**: Pulls data from your Materialized View linked via FDW over the PSC endpoint to `db_remote` over in Cluster B **(Cross-Instance / Inter-Cluster FDW)**.

By running this one `JOIN`, you are simultaneously proving that `db_local` can successfully use `postgres_fdw` to query a second database on the *same* physical machine AND query a third database on an entirely *different* machine, combining them effortlessly!

```sql
SELECT e.name AS employee_name, d.dept_name AS department
FROM local_employees e
JOIN inter_cluster_departments d ON e.department_id = d.id;
```

### 2. Enable `pg_cron` and Robust Logging

Enable `pg_cron` to automate the refresh:

```sql
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- 1. Create Logging Table
CREATE TABLE mv_refresh_log (
    view_name TEXT PRIMARY KEY,
    last_refresh_start TIMESTAMP,
    last_refresh_end TIMESTAMP,
    status TEXT
);

-- 2. Create Wrapper Function
CREATE OR REPLACE FUNCTION refresh_materialized_view_with_log(mview_name TEXT)
RETURNS VOID AS $$
DECLARE
    start_ts TIMESTAMP := clock_timestamp();
BEGIN
    INSERT INTO mv_refresh_log (view_name, last_refresh_start, status)
    VALUES (mview_name, start_ts, 'RUNNING')
    ON CONFLICT (view_name) DO UPDATE 
    SET last_refresh_start = EXCLUDED.last_refresh_start, status = 'RUNNING';

    EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %I', mview_name);

    UPDATE mv_refresh_log 
    SET last_refresh_end = clock_timestamp(), status = 'SUCCESS'
    WHERE view_name = mview_name;
EXCEPTION WHEN OTHERS THEN
    UPDATE mv_refresh_log SET status = 'FAILED' WHERE view_name = mview_name;
    RAISE;
END;
$$ LANGUAGE plpgsql;

-- 3. Schedule Refreshes
SELECT cron.schedule('refresh_employees', '0 2 * * *', 
    'SELECT refresh_materialized_view_with_log(''local_employees'')');

SELECT cron.schedule('refresh_departments', '0 2 * * *', 
    'SELECT refresh_materialized_view_with_log(''inter_cluster_departments'')');
```

### 3. Verify Log

```sql
SELECT * FROM mv_refresh_log;
```

---

## Cleanup

To avoid incurring further charges, clean up the Google Cloud resources created by this POC:

```bash
cd terraform
terraform destroy \
  -var="gcp_project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="alloydb_password=${PASSWORD}"
```

---

## Disclaimer

This code is intended for illustrative purposes and is not an officially supported Google product. It is provided "as is", without warranty of any kind. You should review, test, and adapt these patterns to your specific security and performance requirements before deploying in a production environment.
