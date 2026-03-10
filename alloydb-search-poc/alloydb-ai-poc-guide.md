# AlloyDB AI Vector Search POC Guide

This guide provides an end-to-end, step-by-step walkthrough to set up an AlloyDB Cluster, integrate it with Vertex AI, and perform a vector search. The steps are designed to be runnable from **Cloud Shell** (using `gcloud` and `psql`) or the **AlloyDB Console** (AlloyDB Studio).

## Part 0: Create a New Project (Recommended)

To allow for a smooth setup, avoid IP address or network conflicts, and easily tearn down the environment when you are done, **we strongly recommend creating a fresh Google Cloud Project** for this POC.

1.  **Create Project**: Go to [Manage Resources](https://console.cloud.google.com/cloud-resource-manager) and create a new project (e.g., `alloydb-ai-poc`).
2.  **Enable Billing**: Ensure billing is enabled for the new project.

## Part 1: Setup & Configuration (Cloud Shell)

Run the following commands in Cloud Shell to set up your environment and infrastructure.

### 1. Set Environment Variables
Define the variables for your resources to ensure consistency across commands.

```bash
# 1. Login to Google Cloud
gcloud auth login

# 2. Login to Application Default Credentials (for Python/Client libraries)
gcloud auth application-default login

# 3. Set Project ID
export PROJECT_ID="YOUR_PROJECT_ID" # Replace with your project ID
gcloud config set project ${PROJECT_ID}

# 4. Set Quota Project for ADC (Crucial for Vertex AI API calls)
gcloud auth application-default set-quota-project ${PROJECT_ID}

# 5. Set Common Variables
export REGION="us-central1"
export CLUSTER_ID="alloydb-ai-poc-cluster"
export INSTANCE_ID="alloydb-ai-poc-primary"
export PASSWORD="SuperSecretPassword@123" # Change this!
```

### 2. Enable Required APIs
Enable AlloyDB, Vertex AI, and Service Usage APIs.

```bash
# 2. Enable APIs
gcloud services enable \
  alloydb.googleapis.com \
  aiplatform.googleapis.com \
  compute.googleapis.com \
  servicenetworking.googleapis.com \
  serviceusage.googleapis.com \
  developerknowledge.googleapis.com \
  dns.googleapis.com \
  discoveryengine.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  orgpolicy.googleapis.com \
  --project=${PROJECT_ID}

# 3. Configure Networking (Private Services Access - Required)
# We create a custom VPC to ensure a clean network environment and avoid 'default' network issues.

# 1. Create a custom VPC
gcloud compute networks create alloydb-vpc \
  --project=${PROJECT_ID} \
  --subnet-mode=auto \
  --description="VPC for AlloyDB POC"

# 2. Allocate an IP range for Google services (Private Services Access)
gcloud compute addresses create google-managed-services-alloydb-vpc \
  --global \
  --purpose=VPC_PEERING \
  --prefix-length=16 \
  --description="Peering for AlloyDB" \
  --network=alloydb-vpc \
  --project=${PROJECT_ID}

# 3. Create the private connection
gcloud services vpc-peerings connect \
  --service=servicenetworking.googleapis.com \
  --ranges=google-managed-services-alloydb-vpc \
  --network=alloydb-vpc \
  --project=${PROJECT_ID}

# 4. Export custom routes so AlloyDB can use the PSC endpoint to access custom Vertex AI models
gcloud compute networks peerings update servicenetworking-googleapis-com \
  --network=alloydb-vpc \
  --export-custom-routes \
  --import-custom-routes \
  --project=${PROJECT_ID}

# 4. Configure Private Service Connect (PSC) for Google APIs
# Instead of routing over the public internet (NAT), we use PSC to access Google APIs (Vertex AI) privately.

# 1. Create an IP address for the PSC Endpoint
# address 10.100.0.7 is chosen to avoid conflicts with auto-mode subnets (10.128.0.0/9)
gcloud compute addresses create psc-google-apis-ip \
  --global \
  --purpose=PRIVATE_SERVICE_CONNECT \
  --addresses=10.100.0.7 \
  --network=alloydb-vpc \
  --project=${PROJECT_ID}

# 2. Create the Forwarding Rule to Google APIs
# Note: Name must be 1-20 characters, alphanumeric, with no hyphens.
gcloud compute forwarding-rules create pscgoogleapis \
  --global \
  --target-google-apis-bundle=all-apis \
  --address=psc-google-apis-ip \
  --network=alloydb-vpc \
  --project=${PROJECT_ID}

# 3. Configure DNS to route Google API traffic to the PSC Endpoint
# This ensures AlloyDB uses the private path to reach Vertex AI.

# Create a private DNS zone for googleapis.com
gcloud dns managed-zones create googleapis-private-zone \
  --description="Private DNS context for Google APIs" \
  --dns-name="googleapis.com." \
  --visibility="private" \
  --networks=alloydb-vpc \
  --project=${PROJECT_ID}

# Add the A-record pointing to the PSC IP
PSC_IP=$(gcloud compute addresses describe psc-google-apis-ip --global --format="value(address)" --project=${PROJECT_ID})

gcloud dns record-sets create "googleapis.com." \
  --rrdatas=${PSC_IP} \
  --type=A \
  --ttl=300 \
  --zone=googleapis-private-zone \
  --project=${PROJECT_ID}

gcloud dns record-sets create "*.googleapis.com." \
  --rrdatas="googleapis.com." \
  --type=CNAME \
  --ttl=300 \
  --zone=googleapis-private-zone \
  --project=${PROJECT_ID}
```

### 3. Create AlloyDB Cluster and Instance

```bash

# Create Cluster (Linked to the Custom VPC)
gcloud alloydb clusters create ${CLUSTER_ID} \
  --region=${REGION} \
  --password=${PASSWORD} \
  --network=projects/${PROJECT_ID}/global/networks/alloydb-vpc \
  --project=${PROJECT_ID}


# Get Current IP for Authorized Networks
MY_IP=$(curl -s https://ipv4.icanhazip.com)

# Create Primary Instance (16 vCPU C4A Machine type)
# Enabling public-ip for easier access
# REQUIRED: Set flags for auto-embeddings and ML integration
gcloud alloydb instances create ${INSTANCE_ID} \
  --cluster=${CLUSTER_ID} \
  --region=${REGION} \
  --cpu-count=16 \
  --instance-type=PRIMARY \
  --machine-type=c4a-highmem-16-lssd \
  --authorized-external-networks=${MY_IP}/32 \
  --ssl-mode=ALLOW_UNENCRYPTED_AND_ENCRYPTED \
  --database-flags=google_ml_integration.enable_model_support=on,google_ml_integration.enable_faster_embedding_generation=on,scann.enable_zero_knob_index_creation=on,google_columnar_engine.enabled=on,password.enforce_complexity=on,google_ml_integration.enable_ai_query_engine=on \
  --project=${PROJECT_ID} \
  --assign-inbound-public-ip=ASSIGN_IPV4

```

> **Note**: Creation may take 10-20 minutes.

### 4. Grant Vertex AI Permissions to AlloyDB Service Account
AlloyDB needs permission to call Vertex AI models (e.g., `gemini-embedding-001`) for generating embeddings.

```bash
# Get the AlloyDB Service Agent email
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")
SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com"

# Grant Vertex AI User role
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_AGENT}" \
  --role="roles/aiplatform.user"

# (Optional) Grant Service Usage Consumer if needed for API access
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_AGENT}" \
  --role="roles/serviceusage.serviceUsageConsumer"

# Grant Discovery Engine Viewer for Ranking API
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_AGENT}" \
  --role="roles/discoveryengine.viewer"
```

## Part 2: Database Setup & Vector Search (SQL)

You can run these SQL commands using **AlloyDB Studio** in the [Cloud Console](https://console.cloud.google.com/alloydb/clusters) OR via `psql` in Cloud Shell.

### Option A: Connect via AlloyDB Studio (Console)
1.  Go to the [AlloyDB Clusters page](https://console.cloud.google.com/alloydb/clusters).
2.  Click on your cluster -> Primary Instance.
3.  Click **AlloyDB Studio** in the left menu.
4.  Login with user `postgres` and the password you set.

### Option B: Connect via Cloud Shell (psql)
```bash
# Connect using the postgres user and the instance's Public IP
# You can find the IP with: gcloud alloydb instances describe $INSTANCE_ID --cluster=$CLUSTER_ID --region=$REGION --format="value(ipAddress)"
IP_ADDRESS=$(gcloud alloydb instances describe ${INSTANCE_ID} --cluster=${CLUSTER_ID} --region=${REGION} --format="value(publicIpAddress)")

PGPASSWORD=${PASSWORD} psql -h ${IP_ADDRESS} -U postgres postgres
```

### 1. Enable Extensions
Run the following SQL to enable vector support, machine learning integration, and ScaNN indexing.

> NOTE: You might get an error on the ALTER EXTENSION lines. That's fine. Just ignore it and continue.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER EXTENSION vector UPDATE;
CREATE EXTENSION IF NOT EXISTS alloydb_scann;
ALTER EXTENSION alloydb_scann UPDATE;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;
```

### 2. Verify Vertex AI Integration
Check that the ML integration extension allows access to Vertex AI models.

```sql
-- Version should be 1.5.6+
SELECT extversion FROM pg_extension WHERE extname = 'google_ml_integration';

-- Grant permissions for auto-embedding management (if using a non-superuser)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA google_ml TO postgres;
GRANT USAGE ON SCHEMA ai TO postgres;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ai TO postgres;
GRANT INSERT, UPDATE, DELETE ON google_ml.embed_gen_progress TO postgres;
GRANT INSERT, UPDATE, DELETE ON google_ml.embed_gen_settings TO postgres;

-- TEST: Verify Vertex AI Integration by generating a sample embedding
-- This confirms the Service Account has the correct 'Vertex AI User' role.
-- If you get a permission denied error, wait a minute and try again. It takes time for Vertex AI permissions to propagate.

SELECT embedding('gemini-embedding-001', 'integration test')::vector AS test_embedding;
```

### 3. Load Data
For this POC, we will use the **Marqo-GS-10M** dataset from Hugging Face. To handle the specific schema of this dataset (which includes image URLs, queries, and string IDs), we will use a **Staging Table** approach.

**Dataset Reference**: [Marqo/marqo-GS-10M (Hugging Face)](https://huggingface.co/datasets/Marqo/marqo-GS-10M)

#### A. Download & Prepare Data
1.  Download a subset (e.g., `corpus_1.csv`) from the dataset.

2.  **Important**: The dataset is typically provided in **Parquet** format. You **must convert it to CSV** and remove the header row before uploading.
    
    We will use `uv` to manage Python dependencies for the conversion script.
    
    ```bash
    # Run the conversion script
    # Dependencies (pandas, pyarrow, google-cloud-storage, etc.) are managed by pyproject.toml
    # This script will automatically:
    # 1. Download a subset (data/in_domain-0.parquet) if not found
    # 2. Extract images from the dataset and upload them to your GCS bucket
    # 3. Generate the CSV with GCS URIs for the images
    
    cd alloydb-search-poc/
    export BUCKET_NAME="alloydb-poc-loading-${PROJECT_ID}"
    
    # Create the bucket if it doesn't exist
    gcloud storage buckets create gs://${BUCKET_NAME} --project=${PROJECT_ID} --location=${REGION}
    
    # Convert the dataset to a CSV with GCS URIs for the images
    uv run convert_parquet_to_csv.py --bucket ${BUCKET_NAME}
    ```

3.  Upload the converted CSV to your GCS bucket.
    ```bash
    gcloud storage cp marqo_subset.csv gs://${BUCKET_NAME}/marqo_subset.csv
    ```

> **Note**: The Python script converts the dataset to a CSV with the following columns: `product_id`, `name`, `description`, `category`, `image_url`. The `embedding` column will be populated by the database later.

#### B. Create AlloyDB Table
Create the optimized `product` table. We use `product_id` as the primary key.

```sql
DROP TABLE IF EXISTS product CASCADE;

CREATE TABLE product (
  product_id VARCHAR(255) PRIMARY KEY,
  name TEXT,
  description TEXT,
  category VARCHAR(255),
  image_url TEXT,
  embedding vector(3072) DEFAULT NULL
);
```

#### C. Bulk Import (gcloud)
Use `gcloud` to import the CSV directly into the `product` table.
*   **Important**: This assumes your CSV has **5 columns** in this specific order: `product_id`, `name`, `description`, `category`, `image_url`.
*   We use the `--columns` flag to map input data to specific table columns.

**Reference**: [gcloud alloydb clusters import](https://docs.cloud.google.com/sdk/gcloud/reference/alloydb/clusters/import)

**1. Grant Permissions**
```bash
# Get AlloyDB Service Agent
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")
SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com"

# Grant Storage Object Viewer
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_AGENT}" \
  --role="roles/storage.objectViewer"
```

**2. Run Import**
```bash
gcloud alloydb clusters import ${CLUSTER_ID} \
  --region=${REGION} \
  --gcs-uri=gs://${BUCKET_NAME}/marqo_subset.csv \
  --database=postgres \
  --table=product \
  --columns=product_id,name,description,category,image_url \
  --csv \
  --user=postgres \
  --project=${PROJECT_ID}
```

#### E. Generate Embeddings
Backfill embeddings for the new data.

> **Cost Note**: Generating embeddings for large datasets incurs Vertex AI costs. Estimate your costs here: [Vertex AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing#embedding-models)

```sql
-- Configure and Trigger Auto-Embeddings
CALL ai.initialize_embeddings(
  model_id => 'gemini-embedding-001',
  table_name => 'product',
  content_column => 'description', -- Using description (title) for embedding
  embedding_column => 'embedding',
  batch_size => 50
);

-- Monitor Progress
SELECT * FROM google_ml.embed_gen_progress;
```
> **Tip**: Ensure the backfill is complete (100% progress) **before** creating the ScaNN index.

### 4. Create Auto ScaNN Index
Use AlloyDB's **Auto Indexing** feature to create a self-tuning, self-maintaining index.

**Why this is better:**
1.  **Automatic Configuration**: Analyzes your data to set optimal parameters (like `num_leaves`) without manual tuning.
2.  **Self-Maintenance**: Automatically updates centroids and splits nodes as data grows or distribution drifts.
3.  **Query Optimization**: Uses real-time workload statistics to optimize execution plans.

Run the following to create an index in **AUTO** mode:

```sql
CREATE INDEX product_index ON product
USING scann (embedding cosine)
WITH (mode = 'AUTO');
```

#### Alternative (Manual Method)
For reference, manual index creation requires you to determine and set parameters like `num_leaves`. This is less flexible as data changes.

```sql
-- CREATE INDEX product_index_manual ON product
-- USING scann (embedding cosine)
-- WITH (num_leaves=5);
```

### 5. Perform Vector Search
Find products similar to "soft winter clothes" (Semantic Search).

```sql
-- Simple Vector Search
SELECT product_id, name, description 
FROM product 
ORDER BY embedding <=> embedding('gemini-embedding-001', 'soft winter clothes')::vector 
LIMIT 100;
```

Find "Earmuffs" similar to "Warm and furry" (Filtered Semantic Search).
*Note: We use the `category` column for filtering instead of a separate inventory table.*

```sql
-- Vector Search with Filters
SELECT product_id, name, description, category
FROM product
WHERE category = 'Earmuffs'
ORDER BY embedding <=> embedding('gemini-embedding-001', 'Warm and furry')::vector 
LIMIT 100;
```

### 6. Perform Hybrid Search
Enhance your search by combining vector similarity with traditional keyword-based scoring using weighted Full-Text Search (FTS).

#### Create Weighted Full-text Search Column
Columns are assigned weights (A=Highest, D=Lowest). We'll prioritize `name` (A) and `description` (B).

```sql
ALTER TABLE product ADD COLUMN fts_document tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
  setweight(to_tsvector('english', coalesce(description, '')), 'B')
) STORED;
```

#### Create GIN Index for Efficient Full-text Search
Ref: [Postgres GIN Index Docs](https://www.postgresql.org/docs/current/gin.html)

```sql
CREATE INDEX product_fts_document_gin ON product USING GIN (fts_document);
```

#### Run Hybrid Query (Reciprocal Rank Fusion)
Combine vector search and full-text search results using Reciprocal Rank Fusion (RRF). RRF balances the two methods by using their rank positions rather than raw scores.

```sql
-- Hybrid Search using Reciprocal Rank Fusion (RRF)
WITH vector_search AS (
  SELECT product_id, name, image_url,
         RANK () OVER (ORDER BY embedding <=> embedding('gemini-embedding-001', 'unisex')::vector) AS rank
  FROM product
  ORDER BY embedding <=> embedding('gemini-embedding-001', 'unisex')::vector
  LIMIT 20
),
text_search AS (
  SELECT product_id, name, image_url,
         RANK () OVER (ORDER BY ts_rank(fts_document, to_tsquery('english', 'unisex')) DESC) AS rank
  FROM product
  WHERE fts_document @@ to_tsquery('english', 'unisex')
  ORDER BY ts_rank(fts_document, to_tsquery('english', 'unisex')) DESC
  LIMIT 20
)
SELECT COALESCE(v.product_id, t.product_id) AS product_id,
       COALESCE(v.name, t.name) AS name,
       COALESCE(v.image_url, t.image_url) AS image_url,
       COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score
FROM vector_search v
FULL OUTER JOIN text_search t ON v.product_id = t.product_id
ORDER BY rrf_score DESC
LIMIT 100;
```

### 7. Perform Reranking (Vertex AI)
Re-rank the top predictions using the Vertex AI Ranking API for higher precision. This is a "RAG" (Retrieval Augmented Generation) pattern where you retrieve a larger set (e.g., 20) using fast vector search, and then use a heavier model to re-rank the top results.

**Note:** Ensure you have the `semantic-ranker-512@latest` model enabled in Vertex AI if needed, though typically standard models work out of the box with the API.

```sql
-- Reranking Example with Hybrid Candidates
WITH vector_search AS (
  SELECT product_id, name, description,
         RANK () OVER (ORDER BY embedding <=> embedding('gemini-embedding-001', 'warm fuzzy earmuffs')::vector) AS rank
  FROM product
  ORDER BY embedding <=> embedding('gemini-embedding-001', 'warm fuzzy earmuffs')::vector
  LIMIT 100
),
text_search AS (
  SELECT product_id, name, description,
         RANK () OVER (ORDER BY ts_rank(fts_document, plainto_tsquery('english', 'warm fuzzy earmuffs')) DESC) AS rank
  FROM product
  WHERE fts_document @@ plainto_tsquery('english', 'warm fuzzy earmuffs')
  ORDER BY ts_rank(fts_document, plainto_tsquery('english', 'warm fuzzy earmuffs')) DESC
  LIMIT 100
),
hybrid_candidates AS (
  SELECT COALESCE(v.product_id, t.product_id) AS product_id,
         COALESCE(v.name, t.name) AS name,
         COALESCE(v.description, t.description) AS description,
         COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score,
         ROW_NUMBER() OVER (ORDER BY (COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + t.rank), 0.0)) DESC) AS rank_id
  FROM vector_search v
  FULL OUTER JOIN text_search t ON v.product_id = t.product_id
  ORDER BY rrf_score DESC
  LIMIT 100 -- Top 100 candidates for reranking
),
reranked_results AS (
  -- Use Vertex AI Ranking API to re-score the hybrid candidates
  SELECT index, score
  FROM ai.rank(
    model_id => 'semantic-ranker-512',
    search_string => 'warm fuzzy earmuffs',
    documents => (SELECT ARRAY_AGG(description ORDER BY rank_id) FROM hybrid_candidates),
    top_n => 10
  )
)
-- Join back to get final details
SELECT p.product_id, p.name, p.description, r.score AS rerank_score
FROM hybrid_candidates p
JOIN reranked_results r ON p.rank_id = r.index
ORDER BY r.score DESC;
```

### 8. Bring Your Own Model (BYOM)
Deploy and use custom models (BGE-M3 for embeddings, BGE-Reranker-v2-M3 for reranking) on Vertex AI.

> **Note**: This section requires GPU quota (e.g., L4 or T4) in your Google Cloud project.

#### A. Deploy Models to Vertex AI Endpoint
Use `gcloud` to deploy the models using the Hugging Face Text Embeddings Inference (TEI) container.

```bash
# 1. Set Common Variables
export REGION="us-central1"
export ENDPOINT_ID="bge-m3-endpoint"
export RERANKER_ENDPOINT_ID="bge-reranker-endpoint"
# Using g2-standard-8 (1x L4 GPU) for best performance
export MACHINE_TYPE="g2-standard-8"
export ACCELERATOR_TYPE="nvidia-l4"
export ACCELERATOR_COUNT=1

# The TEI 1.7 container fixes a known bug with relative URLs on HF Hub.
# Vertex AI requires images to be in Artifact Registry, so we mirror it locally.
gcloud artifacts repositories create tei-repo \
  --repository-format=docker \
  --location=${REGION} \
  --project=${PROJECT_ID} || true

# Grant Cloud Build permission to push to Artifact Registry
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/artifactregistry.writer" \
  --condition=None

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer" \
  --condition=None

# Define a Cloud Build configuration to pull and push the image
cat << 'EOF' > cloudbuild.yaml
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['pull', 'ghcr.io/huggingface/text-embeddings-inference:89-1.7']
- name: 'gcr.io/cloud-builders/docker'
  args: ['tag', 'ghcr.io/huggingface/text-embeddings-inference:89-1.7', '$_DESTINATION_IMAGE']
images:
- '$_DESTINATION_IMAGE'
EOF

# Use Cloud Build to mirror the image without needing Docker installed locally
gcloud builds submit --no-source --config cloudbuild.yaml \
  --substitutions=_DESTINATION_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/tei-repo/tei:1.7" \
  --project=${PROJECT_ID}

export CONTAINER_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/tei-repo/tei:1.7"

# 2. Deploy BAAI/bge-m3 (Embeddings)
gcloud ai endpoints create --display-name=bge-m3-endpoint --region=${REGION} --project=${PROJECT_ID}
ENDPOINT_RESOURCE_NAME=$(gcloud ai endpoints list --region=${REGION} --filter="display_name=bge-m3-endpoint" --format="value(name)" --project=${PROJECT_ID})

gcloud ai models upload \
  --container-image-uri=${CONTAINER_URI} \
  --container-env-vars="MODEL_ID=BAAI/bge-m3" \
  --container-ports=80 \
  --container-health-route="/health" \
  --container-predict-route="/embed" \
  --display-name="bge-m3-model" \
  --region=${REGION} \
  --project=${PROJECT_ID}

MODEL_ID=$(gcloud ai models list --region=${REGION} --filter="display_name=bge-m3-model" --format="value(name)" --project=${PROJECT_ID} | head -n 1)

gcloud ai endpoints deploy-model ${ENDPOINT_RESOURCE_NAME} \
  --model=${MODEL_ID} \
  --display-name="bge-m3-deployment" \
  --machine-type=${MACHINE_TYPE} \
  --accelerator="type=${ACCELERATOR_TYPE},count=${ACCELERATOR_COUNT}" \
  --region=${REGION} \
  --project=${PROJECT_ID}

# 3. Deploy BAAI/bge-reranker-v2-m3 (Reranking)
gcloud ai endpoints create --display-name=bge-reranker-endpoint --region=${REGION} --project=${PROJECT_ID}
RERANKER_ENDPOINT_RESOURCE_NAME=$(gcloud ai endpoints list --region=${REGION} --filter="display_name=bge-reranker-endpoint" --format="value(name)" --project=${PROJECT_ID})

gcloud ai models upload \
  --container-image-uri=${CONTAINER_URI} \
  --container-env-vars="MODEL_ID=BAAI/bge-reranker-v2-m3" \
  --container-ports=80 \
  --container-health-route="/health" \
  --container-predict-route="/rerank" \
  --display-name="bge-reranker-model" \
  --region=${REGION} \
  --project=${PROJECT_ID}

RERANKER_MODEL_ID=$(gcloud ai models list --region=${REGION} --filter="display_name=bge-reranker-model" --format="value(name)" --project=${PROJECT_ID} | head -n 1)

gcloud ai endpoints deploy-model ${RERANKER_ENDPOINT_RESOURCE_NAME} \
  --model=${RERANKER_MODEL_ID} \
  --display-name="bge-reranker-deployment" \
  --machine-type=${MACHINE_TYPE} \
  --accelerator="type=${ACCELERATOR_TYPE},count=${ACCELERATOR_COUNT}" \
  --region=${REGION} \
  --project=${PROJECT_ID}
```

#### B. Test Vertex AI Endpoints (Optional but Recommended)
Before registering the models in AlloyDB, it's good practice to verify they are deployed and responding correctly by sending test payloads via `curl`.

```bash
# 1. Test BGE-M3 Embeddings Endpoint
# You should see a JSON response containing an array of floats under "predictions"
curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/endpoints/${ENDPOINT_RESOURCE_NAME}:rawPredict \
  -d '{"inputs": "A warm winter coat"}'

# 2. Test BGE-Reranker-v2-m3 Endpoint
# You should see a JSON response containing an array of scores (floats) under "predictions"
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/endpoints/${RERANKER_ENDPOINT_RESOURCE_NAME}:rawPredict \
  -d '{"query": "winter clothing", "texts": ["A summer t-shirt", "A warm winter coat"]}'
```

#### C. Deploy Cloud Run TEI Translation Proxy

**Why is a proxy necessary?**
We deploy a lightweight Cloud Run proxy to act as a bridge because of a strict compatibility constraint between how AlloyDB authenticates and how Hugging Face TEI processes batch payloads:
1. **The AlloyDB Constraint:** To securely authenticate to Google Vertex AI (`*.googleapis.com`), AlloyDB mandates using the `google` model provider. However, the `google` provider rigidly forces all batch inputs to be wrapped inside an `{"instances": [...]}` JSON array before sending the payload over the network.
2. **The TEI Container Constraint:** The native `ghcr.io` text-embeddings-inference container strictly requires `{"inputs": [...]}` at the highest root level (or `{"query": ...}` for rerankers) on the `:rawPredict` endpoint. It natively rejects the Google `instances` array wrapper with a `missing field 'inputs'` error. 

By registering the model in AlloyDB as a `custom` provider pointing to our proxy, we bypass the `instances` wrapping behavior and send the un-wrapped, correctly-formatted payload directly from our SQL transform sequences. This proxy receives the unauthenticated payload natively, attaches the required Vertex AI IAM Bearer token using its own infrastructure-level service account, and forwards the clean request to the TEI container.

```bash
# 1. Grant compute account access to upload build artifacts and invoke Vertex endpoints
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectViewer" \
  --condition=None

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/aiplatform.user" \
  --condition=None

# 2. Setup proxy codebase
mkdir -p tei-proxy && cd tei-proxy

cat << 'EOF' > requirements.txt
fastapi
uvicorn
httpx
google-auth
requests
EOF

cat << 'EOF' > main.py
import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest

app = FastAPI()

try:
    credentials, project = google.auth.default()
except google.auth.exceptions.DefaultCredentialsError:
    credentials = None

@app.post("/predict/{endpoint_id}")
async def proxy_predict(request: Request, endpoint_id: str):
    payload = await request.json()
    
    # Unpack AlloyDB's internal `{"instances": [ ... ]}` wrapper
    if "instances" in payload and isinstance(payload["instances"], list) and len(payload["instances"]) > 0:
        tei_payload = payload["instances"][0]
    else:
        tei_payload = payload

    if credentials and not credentials.valid:
        credentials.refresh(GoogleAuthRequest())
    
    # Construct Vertex AI URL
    region = os.environ.get("REGION", "us-central1")
    project_id = os.environ.get("PROJECT_ID")
    vertex_url = f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{region}/endpoints/{endpoint_id}:rawPredict"
    
    headers = {"Content-Type": "application/json"}
    if credentials:
        headers["Authorization"] = f"Bearer {credentials.token}"
    
    # Forward payload to Vertex AI TEI container
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(vertex_url, json=tei_payload, headers=headers)
        
    # Wrap TEI array response back into Vertex AI's {"predictions": ...} standard format
    return JSONResponse(
        content={"predictions": response.json()},
        status_code=response.status_code
    )
EOF

# 3. Deploy the proxy
gcloud run deploy tei-proxy \
  --source . \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --allow-unauthenticated \
  --set-env-vars="REGION=${REGION},PROJECT_ID=${PROJECT_ID}" \
  --quiet

# 4. If running in Argolis, you may need to disable org policies blocking external access
cd ..

# Allow all domains for IAM (required for allUsers/unauthenticated Cloud Run)
cat << EOF > policy_iam.yaml
name: projects/${PROJECT_ID}/policies/iam.allowedPolicyMemberDomains
spec:
  rules:
  - allowAll: true
EOF
gcloud org-policies set-policy policy_iam.yaml --project=${PROJECT_ID}

# Wait 60 seconds for org policies to propagate
sleep 60

# Grant public access to Cloud Run (Allowing AlloyDB to bypass IAM enforcement to reach the proxy)
gcloud run services add-iam-policy-binding tei-proxy \
  --region=${REGION} \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --project=${PROJECT_ID}

export PROXY_URL=$(gcloud run services describe tei-proxy --region ${REGION} --format 'value(status.url)')
```

#### D. Get URLs for AlloyDB Registration
Run the following block in your terminal to retrieve the full HTTP proxy URLs configured uniquely for your models. You will replace `YOUR_BGE_M3_PROXY_URL` and `YOUR_RERANKER_PROXY_URL` in the SQL snippet below.

```bash
export BGE_M3_ENDPOINT_ID=$(gcloud ai endpoints list --region=${REGION} --filter="display_name=bge-m3-endpoint" --format="value(name)" --project=${PROJECT_ID} | awk -F/ '{print $NF}')

export RERANKER_ENDPOINT_ID=$(gcloud ai endpoints list --region=${REGION} --filter="display_name=bge-reranker-endpoint" --format="value(name)" --project=${PROJECT_ID} | awk -F/ '{print $NF}')

cat << EOF

--- Endpoint URLs for AlloyDB ---
YOUR_BGE_M3_PROXY_URL:     ${PROXY_URL}/predict/${BGE_M3_ENDPOINT_ID}
YOUR_RERANKER_PROXY_URL:   ${PROXY_URL}/predict/${RERANKER_ENDPOINT_ID}
---------------------------------

EOF
```

#### D. Register Models in AlloyDB
We need to register these endpoints with AlloyDB using `google_ml.create_model`. Since these are custom endpoints, we define **transform functions** to map AlloyDB's SQL input/output to the endpoint's JSON format.

```sql
-- 1. Input Transform for BGE-M3 (Embeddings)
-- Creates native payload {"inputs": ["text"]} for TEI rawPredict
CREATE OR REPLACE FUNCTION bge_m3_input_transform(model_id VARCHAR(100), input_text TEXT)
RETURNS JSON
LANGUAGE plpgsql
AS $$
#variable_conflict use_variable
DECLARE
  transformed_input JSON;
BEGIN
  SELECT json_build_object('inputs', ARRAY[input_text])::JSON INTO transformed_input;
  RETURN transformed_input;
END;
$$;

-- 2. Output Transform for BGE-M3 (Embeddings)
-- Extracts from native nested array [[...]] handled by Cloud Run Proxy
CREATE OR REPLACE FUNCTION bge_m3_output_transform(model_id VARCHAR(100), response_json JSON)
RETURNS REAL[]
LANGUAGE plpgsql
AS $$
DECLARE
  transformed_output REAL[];
BEGIN
  SELECT ARRAY(SELECT json_array_elements_text(response_json->'predictions'->0)::REAL) INTO transformed_output;
  RETURN transformed_output;
END;
$$;

-- 2b. Batch Input Transform for BGE-M3
CREATE OR REPLACE FUNCTION bge_m3_batch_input_transform(model_id VARCHAR(100), input_texts TEXT[])
RETURNS JSON
LANGUAGE plpgsql
AS $$
DECLARE
  transformed_input JSON;
BEGIN
  SELECT json_build_object('inputs', array_to_json(input_texts))::JSON INTO transformed_input;
  RETURN transformed_input;
END;
$$;

-- 2c. Batch Output Transform for BGE-M3
CREATE OR REPLACE FUNCTION bge_m3_batch_output_transform(model_id VARCHAR(100), response_json JSON)
RETURNS REAL[][]
LANGUAGE plpgsql
AS $$
DECLARE
  transformed_output REAL[][];
  row_arr REAL[];
  elem JSON;
BEGIN
    transformed_output := '{}'::REAL[][];
  FOR elem IN SELECT json_array_elements(response_json->'predictions') LOOP
    SELECT ARRAY(SELECT json_array_elements_text(elem)::REAL) INTO row_arr;
    IF array_length(transformed_output, 1) IS NULL THEN
      transformed_output := ARRAY[row_arr];
    ELSE
      transformed_output := array_cat(transformed_output, ARRAY[row_arr]);
    END IF;
  END LOOP;
  RETURN transformed_output;
END;
$$;

-- 3. Register BGE-M3 Model
-- Replace YOUR_PROJECT_ID and YOUR_BGE_M3_PROXY_URL with the values from the terminal output above
CALL google_ml.create_model(
  model_id => 'bge-m3',
  model_request_url => 'YOUR_BGE_M3_PROXY_URL',
  model_provider => 'custom',
  model_type => 'text_embedding',
  model_in_transform_fn => 'bge_m3_input_transform',
  model_out_transform_fn => 'bge_m3_output_transform',
  model_batch_in_transform_fn => 'bge_m3_batch_input_transform',
  model_batch_out_transform_fn => 'bge_m3_batch_output_transform'
);

-- 4. Input Transform for BGE-Reranker (Reranking)
-- Creates native payload {"query": "...", "texts": ["..."]} for TEI rawPredict
CREATE OR REPLACE FUNCTION bge_reranker_input_transform(model_id VARCHAR(100), search_string TEXT, documents TEXT[], top_n INT DEFAULT NULL)
RETURNS JSON
LANGUAGE plpgsql
AS $$
#variable_conflict use_variable
DECLARE
  transformed_input JSON;
BEGIN
  SELECT json_build_object('query', search_string, 'texts', array_to_json(documents))::JSON INTO transformed_input;
  RETURN transformed_input;
END;
$$;

-- 5. Output Transform for BGE-Reranker (Reranking)
-- Maps predictions from [{"index": 0, "score": 0.99}] array handled by proxy
CREATE OR REPLACE FUNCTION bge_reranker_output_transform(model_id VARCHAR(100), response_json JSON)
RETURNS TABLE (index INT, score REAL)
LANGUAGE plpgsql
AS $$
DECLARE
  transformed_output JSON;
BEGIN
  RETURN QUERY
  SELECT (elem->>'index')::INT AS index, (elem->>'score')::REAL AS score
  FROM json_array_elements(response_json->'predictions') AS elem;
END;
$$;

-- 6. Register BGE-Reranker Model
-- Replace YOUR_PROJECT_ID and YOUR_RERANKER_PROXY_URL with the values from the terminal output above
CALL google_ml.create_model(
  model_id => 'bge-reranker-v2-m3',
  model_request_url => 'YOUR_RERANKER_PROXY_URL',
  model_provider => 'custom',
  model_type => 'reranking',
  model_in_transform_fn => 'bge_reranker_input_transform',
  model_out_transform_fn => 'bge_reranker_output_transform'
);

-- 7. Test the Registered Models (Optional but Recommended)
-- Ensure AlloyDB can successfully communicate with your Vertex AI Endpoint
SELECT embedding('bge-m3', 'A warm winter coat');

-- Ensure the ranker can score text correctly
SELECT * FROM ai.rank(
  model_id => 'bge-reranker-v2-m3',
  search_string => 'winter clothing',
  documents => ARRAY['A summer t-shirt', 'A warm winter coat'],
  top_n => 2
);
```

#### E. Compare Results (Gemini vs BGE-M3 vs BGE-Reranker)
Add a column for BGE-M3 embeddings and run a comparison query.

```sql
-- Add column for BGE-M3 embeddings (1024 dimensions)
ALTER TABLE product ADD COLUMN embedding_bge vector(1024) DEFAULT NULL;

-- Initialize BGE-M3 embeddings in batches
CALL ai.initialize_embeddings(
  model_id => 'bge-m3',
  table_name => 'product',
  content_column => 'description',
  embedding_column => 'embedding_bge',
  batch_size => 10
);

-- Monitor Progress
SELECT * FROM google_ml.embed_gen_progress;

-- Create ScaNN Index for BGE-M3
CREATE INDEX product_index_bge_m3 ON product
USING scann (embedding_bge cosine)
WITH (mode = 'AUTO');

-- Compare Search Results
-- 1. Gemini Embedding
SELECT product_id, name, description, 1 - (embedding <=> embedding('gemini-embedding-001', 'warm fuzzy earmuffs')::vector) as score
FROM product
ORDER BY score DESC LIMIT 100;

-- 2. BGE-M3 Embedding
SELECT product_id, name, description, 1 - (embedding_bge <=> embedding('bge-m3', 'warm fuzzy earmuffs')::vector) as score
FROM product
ORDER BY score DESC LIMIT 100;

-- 3. Reranking Top 10 with BGE-Reranker (Using Hybrid Candidates)
WITH vector_search AS (
  SELECT product_id, name, description,
         RANK () OVER (ORDER BY embedding_bge <=> embedding('bge-m3', 'warm fuzzy earmuffs')::vector) as rank
  FROM product
  ORDER BY embedding_bge <=> embedding('bge-m3', 'warm fuzzy earmuffs')::vector
  LIMIT 25
),
text_search AS (
  SELECT product_id, name, description,
         RANK () OVER (ORDER BY ts_rank(fts_document, plainto_tsquery('english', 'warm fuzzy earmuffs')) DESC) AS rank
  FROM product
  WHERE fts_document @@ plainto_tsquery('english', 'warm fuzzy earmuffs')
  ORDER BY ts_rank(fts_document, plainto_tsquery('english', 'warm fuzzy earmuffs')) DESC
  LIMIT 25
),
hybrid_candidates AS (
  SELECT COALESCE(v.product_id, t.product_id) AS product_id,
         COALESCE(v.name, t.name) AS name,
         COALESCE(v.description, t.description) AS description,
         COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score,
         ROW_NUMBER() OVER (ORDER BY (COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + t.rank), 0.0)) DESC) AS rank_id
  FROM vector_search v
  FULL OUTER JOIN text_search t ON v.product_id = t.product_id
  ORDER BY rrf_score DESC
  LIMIT 25
)
SELECT p.product_id, p.name, p.description, r.score
FROM ai.rank(
  model_id => 'bge-reranker-v2-m3',
  search_string => 'warm fuzzy earmuffs',
  documents => (SELECT ARRAY_AGG(description ORDER BY rank_id) FROM hybrid_candidates),
  top_n => 25
) r
JOIN hybrid_candidates p ON r.index = p.rank_id
ORDER BY r.score DESC;
```

> NOTE: Custom models on Vertex AI via `rawPredict` have an implicit ~1.5MB request limit. Large batches of documents (e.g., 100+ descriptions) can easily trigger a `413 Content Too Large` error. We set our top_k to 25 (via LIMIT 25) to avoid this.

### 9. Scaling with Read Pools
To handle high-throughput workloads (like "bid list" uploads) without impacting the primary instance's search performance, use **Read Pool** instances.

1.  **Create a Read Pool**:
    ```bash
    MY_IP=$(curl -s https://ipv4.icanhazip.com)
    gcloud alloydb instances create alloydb-ai-poc-read-pool \
      --cluster=${CLUSTER_ID} \
      --region=${REGION} \
      --instance-type=READ_POOL \
      --cpu-count=8 \
      --read-pool-node-count=2 \
      --project=${PROJECT_ID} \
      --machine-type=c4a-highmem-8-lssd \
      --assign-inbound-public-ip=ASSIGN_IPV4 \
      --database-flags=password.enforce_complexity=on \
      --authorized-external-networks=${MY_IP}/32
    ```

2.  **Connect to Read Pool**:
    Use the Read Pool's IP address for read-only queries (Vector Search).
    ```bash
    READ_POOL_IP=$(gcloud alloydb instances describe alloydb-ai-poc-read-pool --cluster=${CLUSTER_ID} --region=${REGION} --format="value(publicIpAddress)")
    PGPASSWORD=${PASSWORD} psql -h ${READ_POOL_IP} -U postgres postgres
    ```

### 10. Performance Verification
Verify that the solution meets the POC latency and QPS targets.

#### A. Generate Synthetic Data
Scale the dataset to ~100k rows for a more realistic test.

> NOTE: You cannot run INSERTs on a read pool. You must run this on the primary instance.

```sql
-- Generate 100,000 synthetic records
INSERT INTO product (product_id, name, description, category, image_url)
SELECT 
  i::text, 
  'Product ' || i, 
  'Synthetic description for performance testing product number ' || i, 
  'General', 
  'http://example.com/image_' || i
FROM generate_series(100, 100000) AS i;

-- refresh embeddings
CALL ai.refresh_embeddings(
  table_name => 'product',
  embedding_column => 'embedding',
  batch_size => 50
);

CALL ai.refresh_embeddings(
  table_name => 'product',
  embedding_column => 'embedding_bge',
  batch_size => 10
);

-- Monitor Progress
SELECT * FROM google_ml.embed_gen_progress;
```

#### B. Run Benchmark Script
Use this Python script to measure Latency and QPS.

> **Benchmarking Best Practices**: For the most representative performance results, this script should be executed from a **GCE instance** located in the **same region (and ideally the same zone)** as your AlloyDB cluster, connected to the same VPC. This eliminates internet latency and allows you to use AlloyDB's **internal IP**, providing a true measurement of the database's performance.

1. **Set up benchmark environment**

```bash
# Create a separate configuration for the benchmark to avoid modifying the main project's dependencies:
cat << EOF > benchmark.toml
[project]
name = "alloydb-benchmark"
version = "0.1.0"
dependencies = [
    "psycopg2-binary",
    "numpy",
    "google-cloud-aiplatform",
]
EOF

# Install Dependencies:
# Use the --project flag to specify the benchmark-specific configuration
uv sync --project benchmark.toml

# Get the Internal IP of your Read Pool
export ALLOYDB_INTERNAL_IP=$(gcloud alloydb instances describe alloydb-ai-poc-read-pool \
  --cluster=${CLUSTER_ID} --region=${REGION} --format="value(ipAddress)")

# Create `benchmark.py`
cat << EOF > benchmark.py
import time
import psycopg2
import numpy as np
import threading
import argparse
import sys

# Database Configuration
DB_HOST = "${ALLOYDB_INTERNAL_IP}" 
DB_USER = "postgres"
DB_PASS = "${PASSWORD}"
DB_NAME = "postgres"

# Mapping of search types to their database column and model ID
SEARCH_CONFIG = {
    "gemini": {
        "column": "embedding",
        "model_id": "gemini-embedding-001"
    },
    "bge": {
        "column": "embedding_bge",
        "model_id": "bge-m3"
    }
}

# Global list to store latencies from all threads
latencies = []
latency_lock = threading.Lock()

def get_connection():
    return psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, dbname=DB_NAME)

def worker(num_queries, search_type):
    config = SEARCH_CONFIG[search_type]
    column = config["column"]
    model_id = config["model_id"]
    
    conn = get_connection()
    cur = conn.cursor()
    
    # 1. Get a dummy vector first to use in PREPARE
    cur.execute(f"SELECT embedding('{model_id}', 'performance test')::vector")
    query_vector = cur.fetchone()[0]
    
    # 2. Prepare the statement
    cur.execute(f"PREPARE search_plan (vector) AS SELECT product_id FROM product ORDER BY {column} <=> \$1 LIMIT 100")
    
    local_latencies = []
    
    for _ in range(num_queries):
        start = time.time()
        cur.execute("EXECUTE search_plan (%s)", (query_vector,))
        cur.fetchall()
        lat = (time.time() - start) * 1000 # ms
        local_latencies.append(lat)
        
    cur.close()
    conn.close()
    
    with latency_lock:
        latencies.extend(local_latencies)

def benchmark(search_type, total_requests=1000, concurrency=10):
    print(f"Starting {search_type} benchmark: {total_requests} requests, {concurrency} threads...")
    
    threads = []
    queries_per_thread = total_requests // concurrency
    
    start_time = time.time()
    
    for _ in range(concurrency):
        t = threading.Thread(target=worker, args=(queries_per_thread, search_type))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()

    total_time = time.time() - start_time
    qps = total_requests / total_time
    
    print(f"Model: {search_type} ({SEARCH_CONFIG[search_type]['model_id']})")
    print(f"P50 Latency: {np.percentile(latencies, 50):.2f} ms")
    print(f"P95 Latency: {np.percentile(latencies, 95):.2f} ms")
    print(f"QPS: {qps:.2f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AlloyDB Vector Search Benchmark")
    parser.add_argument("--type", choices=["gemini", "bge"], default="gemini", help="Type of embedding to benchmark")
    parser.add_argument("--requests", type=int, default=1000, help="Total number of requests")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of concurrent threads")
    
    args = parser.parse_args()
    
    benchmark(args.type, args.requests, args.concurrency)
EOF
```

2. **Set Up a GCE Benchmark Client**
Run these commands in Cloud Shell to create a client instance in the same VPC.

```bash
# 1. Allow GCE External IP Access & IAP Tunneling
# Disabling policies that block external IPs (required for the client)
cat << EOF > policy_gce.yaml
name: projects/${PROJECT_ID}/policies/compute.vmExternalIpAccess
spec:
  rules:
  - allowAll: true
  inheritFromParent: false
EOF
gcloud org-policies set-policy policy_gce.yaml --project=${PROJECT_ID}

# Grant yourself permission to use IAP Tunneling
# Replace YOUR_EMAIL with your GCP login email
export MY_EMAIL=$(gcloud config get-value account)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="user:${MY_EMAIL}" \
  --role="roles/iap.tunnelResourceAccessor"

# Wait 60 seconds for org policies to propagate
sleep 60

# 2. Create the instance
gcloud compute instances create benchmark-client \
  --zone=${REGION}-a \
  --network=alloydb-vpc \
  --machine-type=e2-medium \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --scopes=cloud-platform \
  --shielded-secure-boot \
  --project=${PROJECT_ID}

# 3. Allow SSH/SCP access (Local IP + IAP Tunneling)
# Direct access for your local IP
MY_IP=$(curl -s https://ipv4.icanhazip.com)
gcloud compute firewall-rules create allow-ssh-from-local \
  --network=alloydb-vpc --allow=tcp:22 --source-ranges=${MY_IP}/32 \
  --priority=100 --project=${PROJECT_ID}

# IAP Tunneling access (Mandatory for IAP-based SSH/SCP)
gcloud compute firewall-rules create allow-ssh-from-iap \
  --network=alloydb-vpc --allow=tcp:22 --source-ranges=35.235.240.0/20 \
  --priority=100 --project=${PROJECT_ID}

# Sleep 60 seconds for firewall rules to propagate
sleep 60

# 4. SCP the benchmark files to the instance
# Using --tunnel-through-iap for maximum reliability
gcloud compute scp benchmark.toml benchmark.py benchmark-client:~/ \
  --zone=${REGION}-a --project=${PROJECT_ID} --tunnel-through-iap
```

3. **Run the Benchmark on the Instance**
SSH into the client to install dependencies and execute the script.

```bash
# 1. SSH into the instance
gcloud compute ssh benchmark-client --zone=${REGION}-a --project=${PROJECT_ID} --tunnel-through-iap

# 2. Install uv (Python manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 3. Synchronize environment and run
# We rename to pyproject.toml to simplify the setup
mv benchmark.toml pyproject.toml
uv sync

# Run Gemini Benchmark
uv run python benchmark.py --type gemini

# Run BGE Benchmark
uv run python benchmark.py --type bge
```

## Cleanup

1.  **Delete AlloyDB Cluster**:
    ```bash
    gcloud alloydb clusters delete ${CLUSTER_ID} --region=${REGION} --force --project=${PROJECT_ID}
    ```

2.  **Delete Vertex AI Endpoints & Models**:
    *   **Option A (Console)**: Go to [Vertex AI Online Prediction](https://console.cloud.google.com/vertex-ai/online-prediction/endpoints), undeploy models from endpoints, delete endpoints, then delete models in [Model Registry](https://console.cloud.google.com/vertex-ai/models).
    *   **Option B (CLI)**:
        ```bash
        # Helper function to cleanup an endpoint
        cleanup_endpoint() {
          DISPLAY_NAME=$1
          echo "Cleaning up $DISPLAY_NAME..."
          EP_NAME=$(gcloud ai endpoints list --region=${REGION} --filter="display_name=${DISPLAY_NAME}" --format="value(name)" --project=${PROJECT_ID} | head -n1)
          if [ -n "$EP_NAME" ]; then
            # Undeploy all models
            for DEPLOYED_ID in $(gcloud ai endpoints describe $EP_NAME --region=${REGION} --format="value(deployedModels.id)" --project=${PROJECT_ID} | tr ';' ' '); do
              echo "Undeploying $DEPLOYED_ID..."
              gcloud ai endpoints undeploy-model $EP_NAME --deployed-model-id=$DEPLOYED_ID --region=${REGION} --project=${PROJECT_ID} --quiet
            done
            # Delete endpoint
            echo "Deleting endpoint..."
            gcloud ai endpoints delete $EP_NAME --region=${REGION} --project=${PROJECT_ID} --quiet
          fi
        }

        # Run Cleanup
        cleanup_endpoint "bge-m3-endpoint"
        cleanup_endpoint "bge-reranker-endpoint"

        # Delete Models
        gcloud ai models list --region=${REGION} --filter="display_name=bge-m3-model" --format="value(name)" --project=${PROJECT_ID} | xargs -r gcloud ai models delete --region=${REGION} --project=${PROJECT_ID} --quiet
        gcloud ai models list --region=${REGION} --filter="display_name=bge-reranker-model" --format="value(name)" --project=${PROJECT_ID} | xargs -r gcloud ai models delete --region=${REGION} --project=${PROJECT_ID} --quiet
        ```

## References

*   [Grant IAM permissions for Vertex AI](https://docs.cloud.google.com/alloydb/docs/ai/configure-vertex-ai#grant-iam-permissions)
*   [Import a CSV file into AlloyDB](https://docs.cloud.google.com/alloydb/docs/import-csv-file)
*   [Perform a vector search](https://docs.cloud.google.com/alloydb/docs/ai/perform-vector-search)
*   [Auto vector embeddings and auto vector index (Blog)](https://cloud.google.com/blog/products/databases/alloydb-ai-auto-vector-embeddings-and-auto-vector-index)
*   [Generate and manage auto vector embeddings for large tables](https://docs.cloud.google.com/alloydb/docs/ai/generate-manage-auto-embeddings-for-tables)
*   [Create a ScaNN index](https://docs.cloud.google.com/alloydb/docs/ai/create-scann-index)
*   [Embeddings Batch Processing Notebook (GitHub)](https://github.com/GoogleCloudPlatform/python-docs-samples/blob/main/alloydb/notebooks/embeddings_batch_processing.ipynb)
*   [Run a hybrid vector similarity search](https://docs.cloud.google.com/alloydb/docs/ai/run-hybrid-vector-similarity-search)
*   [Hybrid Search Example (GitHub)](https://github.com/paulramsey/stylesearch-alloydb-ai-demo/blob/main/cymbal_shops_hybrid_search_alloydb_data_prep.ipynb)
*   [Rank and rerank search results](https://docs.cloud.google.com/alloydb/docs/ai/rank-rerank-search-results-rag)
*   [Vertex AI Ranking API (Agent Builder)](https://docs.cloud.google.com/generative-ai-app-builder/docs/ranking)
*   [Register and call remote AI models](https://docs.cloud.google.com/alloydb/docs/ai/register-model-endpoint)
*   [BAAI/bge-m3 (Hugging Face)](https://huggingface.co/BAAI/bge-m3)
*   [BAAI/bge-reranker-v2-m3 (Hugging Face)](https://huggingface.co/BAAI/bge-reranker-v2-m3)
*   [BGE FlagEmbedding (GitHub)](https://github.com/FlagOpen/FlagEmbedding)
*   [Marqo/marqo-GS-10M (Hugging Face)](https://huggingface.co/datasets/Marqo/marqo-GS-10M)
*   [Create an AlloyDB Read Pool](https://docs.cloud.google.com/alloydb/docs/instance-read-pool-create#gcloud)
*   [Choose an AlloyDB machine type](https://docs.cloud.google.com/alloydb/docs/choose-machine-type)

