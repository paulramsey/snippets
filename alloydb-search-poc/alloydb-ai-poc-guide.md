# AlloyDB AI Vector Search POC Guide

This guide provides an end-to-end, step-by-step walkthrough to set up an AlloyDB Cluster, integrate it with Vertex AI, and perform a vector search. The steps are designed to be runnable from **Cloud Shell** (using `gcloud` and `psql`) or the **AlloyDB Console** (AlloyDB Studio).

## Prerequisites

1.  **Google Cloud Project**: Ensure you have a project with billing enabled.
2.  **Cloud Shell**: Open [Cloud Shell](https://shell.cloud.google.com/).
3.  **APIs**: Enable the required APIs.
4.  **Database Flags**: Ensure `google_ml_integration.enable_model_support=on`, `google_ml_integration.enable_faster_embedding_generation=on`, and `scann.enable_zero_knob_index_creation=on` are set (done in the creation step below).

## Part 1: Setup & Configuration (Cloud Shell)

Run the following commands in Cloud Shell to set up your environment and infrastructure.

### 1. Set Environment Variables
Define the variables for your resources to ensure consistency across commands.

```bash
export PROJECT_ID=$(gcloud config get-value project)
export REGION="us-central1"
export CLUSTER_ID="alloydb-ai-poc-cluster"
export INSTANCE_ID="alloydb-ai-poc-primary"
export PASSWORD="supersecretpassword" # Change this!
```

### 2. Enable Required APIs
Enable AlloyDB, Vertex AI, and Service Usage APIs.

```bash
gcloud services enable \
  alloydb.googleapis.com \
  aiplatform.googleapis.com \
  serviceusage.googleapis.com \
  --project=${PROJECT_ID}
```

### 3. Create AlloyDB Cluster and Instance
Create a cluster and a primary instance. We enable **Public IP** to simplify connectivity from Cloud Shell (or external tools) for this POC.

```bash
# Create Cluster
gcloud alloydb clusters create ${CLUSTER_ID} \
  --region=${REGION} \
  --password=${PASSWORD} \
  --project=${PROJECT_ID}


# Create Primary Instance (8 vCPU C4A Machine type)
# Enabling public-ip for easier access
# REQUIRED: Set flags for auto-embeddings and ML integration
gcloud alloydb instances create ${INSTANCE_ID} \
  --cluster=${CLUSTER_ID} \
  --region=${REGION} \
  --cpu-count=16 \
  --machine-type=c4a-highmem-16 \
  --assign-ip \
  --ssl-mode=ALLOW_UNENCRYPTED_AND_ENCRYPTED \
  --database-flags=google_ml_integration.enable_model_support=on,google_ml_integration.enable_faster_embedding_generation=on,scann.enable_zero_knob_index_creation=on,google_columnar_engine.enabled=on \
  --project=${PROJECT_ID}

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
IP_ADDRESS=$(gcloud alloydb instances describe ${INSTANCE_ID} --cluster=${CLUSTER_ID} --region=${REGION} --format="value(ipAddress)")

PGPASSWORD=${PASSWORD} psql -h ${IP_ADDRESS} -U postgres postgres
```

### 1. Enable Extensions
Run the following SQL to enable vector support, machine learning integration, and ScaNN indexing.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER EXTENSION vector UPDATE;
CREATE EXTENSION IF NOT EXISTS alloydb_scann;
ALTER EXTENSION alloydb_scann UPDATE;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;
ALTER EXTENSION google_ml_integration UPDATE;
```

### 2. Verify Vertex AI Integration
Check that the ML integration extension allows access to Vertex AI models.

```sql
SELECT extversion FROM pg_extension WHERE extname = 'google_ml_integration';

-- Grant permissions for auto-embedding management (if using a non-superuser)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA google_ml TO postgres;
GRANT INSERT, UPDATE, DELETE ON google_ml.embed_gen_progress TO postgres;
GRANT INSERT, UPDATE, DELETE ON google_ml.embed_gen_settings TO postgres;

```

### 3. Load Data
For this POC, we will use the **Marqo-GS-10M** dataset from Hugging Face. To handle the specific schema of this dataset (which includes image URLs, queries, and string IDs), we will use a **Staging Table** approach.

**Dataset Reference**: [Marqo/marqo-GS-10M (Hugging Face)](https://huggingface.co/datasets/Marqo/marqo-GS-10M)

#### A. Download & Prepare Data
1.  Download a subset (e.g., `corpus_1.csv`) from the dataset.
2.  **Important**: The dataset is typically provided in **Parquet** format. You **must convert it to CSV** and remove the header row before uploading, as `gcloud import` requires CSV format and strictly matches columns.
3.  Upload the converted CSV to your GCS bucket (e.g., `gs://your-bucket/marqo_subset.csv`).

> **Note**: This strategy assumes the CSV matches the Marqo dataset schema (headers: `image`, `query`, `product_id`, `position`, `title`, `paix_id`, `score_linear`, `score_reciprocal`, `no_score`, `query_id`).

#### B. Create Staging Table
Create a temporary table that matches the CSV columns primarily to facilitate the import.

```sql
DROP TABLE IF EXISTS marqo_staging;

CREATE TABLE marqo_staging (
    image TEXT,
    query TEXT,
    product_id TEXT,
    position INT,
    title TEXT,
    paix_id TEXT,
    score_linear INT,
    score_reciprocal FLOAT,
    no_score INT,
    query_id TEXT
);
```

#### C. Bulk Import (gcloud)
Use `gcloud` to import the CSV into the staging table.

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
  --gcs-uri=gs://your-bucket/path/to/marqo_subset.csv \
  --database=postgres \
  --table=marqo_staging \
  --csv \
  --user=postgres \
  --project=${PROJECT_ID}
```

#### D. Transform & Load to Final Table
Create the optimized `product` table and populate it from the staging table. We add a **surrogate primary key** (`id`) for efficient indexing and storage, while keeping the original ID as `product_id`.

```sql
-- 1. Create Final Table
DROP TABLE IF EXISTS product CASCADE;

CREATE TABLE product (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  product_id VARCHAR(255),
  name TEXT,
  description TEXT,
  category VARCHAR(255),
  image_url TEXT,
  embedding vector(768) DEFAULT NULL
);

-- 2. Insert Data (Transform)
-- Map: product_id -> product_id, title -> name, title -> description (as proxy), query -> category
-- We EXCLUDE 'id' to allow PostgreSQL to auto-generate the surrogate key.
INSERT INTO product (product_id, name, description, category, image_url)
SELECT 
    DISTINCT product_id, 
    title, 
    title, -- Using title as description since dataset lacks long text
    query, 
    image
FROM marqo_staging
ON CONFLICT DO NOTHING; -- Handle potential duplicates if constraint existed (no unique on product_id yet, but good practice)

-- 3. Cleanup Staging
DROP TABLE marqo_staging;
```

#### E. Generate Embeddings
Backfill embeddings for the new data.

```sql
-- Configure and Trigger Auto-Embeddings
SELECT ai.initialize_embeddings(
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
Find products similar to "music" (semantic search).

```sql
-- Simple Vector Search
SELECT product_id, name, description 
FROM product 
ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector 
LIMIT 3;
```

Find "Toys" similar to "music" (Filtered Search).
*Note: We use the `category` column for filtering instead of a separate inventory table.*

```sql
-- Vector Search with Filters
SELECT product_id, name, description, category
FROM product
WHERE category = 'Toys'
ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector 
LIMIT 3;
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
  SELECT id, product_id,
         RANK () OVER (ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector) AS rank
  FROM product
  ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector
  LIMIT 20
),
text_search AS (
  SELECT id, product_id,
         RANK () OVER (ORDER BY ts_rank(fts_document, to_tsquery('english', 'music')) DESC) AS rank
  FROM product
  WHERE fts_document @@ to_tsquery('english', 'music')
  ORDER BY ts_rank(fts_document, to_tsquery('english', 'music')) DESC
  LIMIT 20
)
SELECT COALESCE(v.product_id, t.product_id) AS product_id,
       COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score
FROM vector_search v
FULL OUTER JOIN text_search t ON v.id = t.id
ORDER BY rrf_score DESC
LIMIT 5;
```

### 7. Perform Reranking (Vertex AI)
Re-rank the top predictions using the Vertex AI Ranking API for higher precision. This is a "RAG" (Retrieval Augmented Generation) pattern where you retrieve a larger set (e.g., 20) using fast vector search, and then use a heavier model to re-rank the top results.

**Note:** Ensure you have the `semantic-ranker-512@latest` model enabled in Vertex AI if needed, though typically standard models work out of the box with the API.

```sql
-- Reranking Example
WITH initial_retrieval AS (
  -- 1. Retrieve top 10 candidates using fast vector search
  SELECT id, product_id, name, description,
         ROW_NUMBER() OVER () AS rank_id
  FROM product
  ORDER BY embedding <=> embedding('gemini-embedding-001', 'toys for kids')::vector
  LIMIT 10
),
reranked_results AS (
  -- 2. Use Vertex AI Ranking API to re-score the candidates
  SELECT index, score
  FROM ai.rank(
    model_id => 'semantic-ranker-default@latest',
    search_string => 'toys for kids',
    documents => (SELECT ARRAY_AGG(description ORDER BY rank_id) FROM initial_retrieval),
    top_n => 5
  )
)
-- 3. Join back to get final details
SELECT p.product_id, p.name, p.description, r.score AS rerank_score
FROM initial_retrieval p
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
export ACCELERATOR_TYPE="NVIDIA_L4"
export ACCELERATOR_COUNT=1
export CONTAINER_URI="us-docker.pkg.dev/deeplearning-platform-release/gcr.io/huggingface-text-embeddings-inference-cu122.1-4.ubuntu2204"

# 2. Deploy BAAI/bge-m3 (Embeddings)
gcloud ai endpoints create --display-name=${ENDPOINT_ID} --region=${REGION} --project=${PROJECT_ID}
ENDPOINT_RESOURCE_NAME=$(gcloud ai endpoints list --region=${REGION} --filter="display_name=${ENDPOINT_ID}" --format="value(name)" --project=${PROJECT_ID})

gcloud ai models upload \
  --container-image-uri=${CONTAINER_URI} \
  --container-env-vars="MODEL_ID=BAAI/bge-m3" \
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
gcloud ai endpoints create --display-name=${RERANKER_ENDPOINT_ID} --region=${REGION} --project=${PROJECT_ID}
RERANKER_ENDPOINT_RESOURCE_NAME=$(gcloud ai endpoints list --region=${REGION} --filter="display_name=${RERANKER_ENDPOINT_ID}" --format="value(name)" --project=${PROJECT_ID})

gcloud ai models upload \
  --container-image-uri=${CONTAINER_URI} \
  --container-env-vars="MODEL_ID=BAAI/bge-reranker-v2-m3" \
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

#### B. Register Models in AlloyDB
We need to register these endpoints with AlloyDB using `google_ml.create_model`. Since these are custom endpoints, we define **transform functions** to map AlloyDB's SQL input/output to the endpoint's JSON format.

```sql
-- 1. Input Transform for BGE-M3 (Embeddings)
-- Wraps input text into {"instances": ["text"]}
CREATE OR REPLACE FUNCTION bge_m3_input_transform(model_id VARCHAR(100), input_text TEXT)
RETURNS JSON
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN json_build_object('instances', json_build_array(input_text));
END;
$$;

-- 2. Output Transform for BGE-M3 (Embeddings)
-- Extracts embedding from {"predictions": [[...]]}
CREATE OR REPLACE FUNCTION bge_m3_output_transform(model_id VARCHAR(100), response_json JSON)
RETURNS REAL[]
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN ARRAY(SELECT json_array_elements_text(response_json->'predictions'->0));
END;
$$;

-- 3. Register BGE-M3 Model
-- Replace ENDPOINT_ID with your actual Vertex AI Endpoint ID (numeric)
-- Get it via: gcloud ai endpoints list --region=us-central1 --filter="display_name=bge-m3-endpoint"
CALL google_ml.create_model(
  model_id => 'bge-m3',
  model_request_url => 'https://us-central1-aiplatform.googleapis.com/v1/projects/' || current_setting('google_ml_integration.project_id') || '/locations/us-central1/endpoints/YOUR_BGE_M3_ENDPOINT_ID:predict',
  model_provider => 'custom',
  model_type => 'text_embedding',
  model_in_transform_fn => 'bge_m3_input_transform',
  model_out_transform_fn => 'bge_m3_output_transform'
);

-- 4. Input Transform for BGE-Reranker (Reranking)
-- Wraps input into {"instances": [{"query": "q", "text": "d"}, ...]}
CREATE OR REPLACE FUNCTION bge_reranker_input_transform(model_id VARCHAR(100), search_string TEXT, documents TEXT[], top_n INT DEFAULT NULL)
RETURNS JSON
LANGUAGE plpgsql
AS $$
DECLARE
  instances JSON;
BEGIN
  SELECT json_agg(json_build_object('query', search_string, 'text', doc))
  INTO instances
  FROM unnest(documents) AS doc;
  
  RETURN json_build_object('instances', instances);
END;
$$;

-- 5. Output Transform for BGE-Reranker (Reranking)
-- Maps predictions to (index, score) pairs
CREATE OR REPLACE FUNCTION bge_reranker_output_transform(model_id VARCHAR(100), response_json JSON)
RETURNS TABLE (index INT, score REAL)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT (row_number() OVER ())::INT AS index, (elem::text)::REAL AS score
  FROM json_array_elements(response_json->'predictions') AS elem;
END;
$$;

-- 6. Register BGE-Reranker Model
-- Replace YOUR_RERANKER_ENDPOINT_ID with actual numeric ID
CALL google_ml.create_model(
  model_id => 'bge-reranker-v2-m3',
  model_request_url => 'https://us-central1-aiplatform.googleapis.com/v1/projects/' || current_setting('google_ml_integration.project_id') || '/locations/us-central1/endpoints/YOUR_RERANKER_ENDPOINT_ID:predict',
  model_provider => 'custom',
  model_type => 'reranking',
  model_in_transform_fn => 'bge_reranker_input_transform',
  model_out_transform_fn => 'bge_reranker_output_transform'
);
```

#### C. Compare Results (Gemini vs BGE-M3 vs BGE-Reranker)
Add a column for BGE-M3 embeddings and run a comparison query.

```sql
-- Add column for BGE-M3 embeddings (1024 dimensions)
ALTER TABLE product ADD COLUMN embedding_bge vector(1024) DEFAULT NULL;

-- Initialize BGE-M3 embeddings
SELECT ai.initialize_embeddings(
  model_id => 'bge-m3',
  table_name => 'product',
  content_column => 'description',
  embedding_column => 'embedding_bge',
  batch_size => 50
);

-- Compare Search Results
-- 1. Gemini Embedding
SELECT product_id, name, description, 1 - (embedding <=> embedding('gemini-embedding-001', 'music')::vector) as score
FROM product
ORDER BY score DESC LIMIT 3;

-- 2. BGE-M3 Embedding
SELECT product_id, name, description, 1 - (embedding_bge <=> embedding('bge-m3', 'music')::vector) as score
FROM product
ORDER BY score DESC LIMIT 3;

-- 3. Reranking Top 10 with BGE-Reranker
WITH candidates AS (
  SELECT id, product_id, name, description,
         ROW_NUMBER() OVER (ORDER BY embedding_bge <=> embedding('bge-m3', 'music')::vector) as rank_id
  FROM product
  ORDER BY embedding_bge <=> embedding('bge-m3', 'music')::vector
  LIMIT 10
)
SELECT p.product_id, p.name, p.description, r.score
FROM ai.rank(
  model_id => 'bge-reranker-v2-m3',
  search_string => 'music',
  documents => (SELECT ARRAY_AGG(description ORDER BY rank_id) FROM candidates),
  top_n => 3
) r
JOIN candidates p ON r.index = p.rank_id;
```

```

### 9. Fine-Tune Your Models (Optional)
Improve performance on your specific domain by fine-tuning the models.

#### A. Preparation
Install the required libraries:
```bash
pip install -U FlagEmbedding[finetune] transformers torch
```

**Data Format (JSONL):**
*   **Embeddings**: `{"query": "text", "pos": ["positive text"], "neg": ["negative text"]}`
*   **Reranker**: `{"query": "text", "pos": ["positive text"], "neg": ["negative text"]}`

#### B. Fine-Tune BGE-M3 (Embeddings)
Use `torchrun` to fine-tune the embedding model.

```bash
torchrun --nproc_per_node 1 \
-m FlagEmbedding.baai_general_embedding.finetune.run \
--output_dir ./bge-m3-finetuned \
--model_name_or_path BAAI/bge-m3 \
--train_data ./train.jsonl \
--learning_rate 1e-5 \
--fp16 \
--num_train_epochs 5 \
--per_device_train_batch_size 4 \
--dataloader_drop_last True \
--normlized True \
--temperature 0.02 \
--query_max_len 512 \
--passage_max_len 512 \
--train_group_size 2 \
--negatives_cross_device \
--logging_steps 10 \
--save_steps 1000 \
--save_total_limit 2
```

#### C. Fine-Tune BGE-Reranker
Use `torchrun` to fine-tune the reranker.

```bash
torchrun --nproc_per_node 1 \
-m FlagEmbedding.reranker.run \
--output_dir ./bge-reranker-finetuned \
--model_name_or_path BAAI/bge-reranker-v2-m3 \
--train_data ./train.jsonl \
--learning_rate 2e-5 \
--fp16 \
--num_train_epochs 3 \
--per_device_train_batch_size 1 \
--gradient_accumulation_steps 4 \
--train_group_size 4 \
--max_len 512 \
--weight_decay 0.01 \
--logging_steps 10 \
--save_steps 1000 \
--save_total_limit 2
```

#### D. Upload to Hugging Face
Once trained, upload your model to Hugging Face to deploy it using the steps in **Part 8**.

```bash
pip install huggingface_hub
huggingface-cli login

# Upload Embeddings Model
huggingface-cli upload your-username/bge-m3-custom ./bge-m3-finetuned

# Upload Reranker Model
huggingface-cli upload your-username/bge-reranker-custom ./bge-reranker-finetuned
```

**Deploy:** Update the `MODEL_ID` in **Part 8** to `your-username/bge-m3-custom` or `your-username/bge-reranker-custom`.

```

### 10. Scaling with Read Pools
To handle high-throughput workloads (like "bid list" uploads) without impacting the primary instance's search performance, use **Read Pool** instances.

1.  **Create a Read Pool**:
    ```bash
    gcloud alloydb instances create alloydb-ai-poc-read-pool \
      --cluster=${CLUSTER_ID} \
      --region=${REGION} \
      --instance-type=READ_POOL \
      --cpu-count=8 \
      --read-pool-node-count=2 \
      --assign-ip \
      --project=${PROJECT_ID}
    ```

2.  **Connect to Read Pool**:
    Use the Read Pool's IP address for read-only queries (Vector Search).
    ```bash
    READ_POOL_IP=$(gcloud alloydb instances describe alloydb-ai-poc-read-pool --cluster=${CLUSTER_ID} --region=${REGION} --format="value(ipAddress)")
    PGPASSWORD=${PASSWORD} psql -h ${READ_POOL_IP} -U postgres postgres
    ```

### 11. Performance Verification
Verify that the solution meets the POC latency (<20ms) and QPS (>25) targets.

#### A. Generate Synthetic Data
Scale the dataset to ~100k rows for a more realistic test (13.6M requires more time/storage).

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

-- Wait for auto-embeddings to catch up
SELECT count(*) FROM product WHERE embedding IS NOT NULL;
```

#### B. Run Benchmark Script
Use this Python script to measure Latency and QPS.

1.  **Install Dependencies**:
    ```bash
    pip install psycopg2-binary numpy google-cloud-aiplatform
    ```

2.  **Create `benchmark.py`**:
    ```python
    import time
    import psycopg2
    import numpy as np
    import threading

    DB_HOST = "YOUR_ALLOYDB_IP" # Use Primary or Read Pool IP
    DB_USER = "postgres"
    DB_PASS = "supersecretpassword"
    DB_NAME = "postgres"

    # Global list to store latencies from all threads
    latencies = []
    latency_lock = threading.Lock()

    def get_connection():
        return psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, dbname=DB_NAME)

    def worker(num_queries):
        conn = get_connection()
        cur = conn.cursor()
        
        # PREPARE the statement once per connection
        # We pre-calculate the query embedding here for the benchmark to isolate search performance.
        # In a real app, the embedding generation might be separate or passed as a parameter.
        # For this test: ORDER BY embedding <=> (vector)
        # Note: We hardcode a vector for the prepared statement or pass it as a param.
        # Let's pass it as a parameter to simulate real-world behavior of receiving a query vector.
        
        # 1. Get a dummy vector first to use in PREPARE (or just prepare with a placeholder)
        cur.execute("SELECT embedding('gemini-embedding-001', 'performance test')::vector")
        query_vector = cur.fetchone()[0]
        
        # 2. Prepare the statement
        cur.execute(f"PREPARE search_plan (vector) AS SELECT id FROM product ORDER BY embedding <=> $1 LIMIT 10")
        
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

    def benchmark(total_requests=1000, concurrency=10):
        print(f"Starting benchmark: {total_requests} requests, {concurrency} threads...")
        
        threads = []
        queries_per_thread = total_requests // concurrency
        
        start_time = time.time()
        
        for _ in range(concurrency):
            t = threading.Thread(target=worker, args=(queries_per_thread,))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()

        total_time = time.time() - start_time
        qps = total_requests / total_time
        
        print(f"P50 Latency: {np.percentile(latencies, 50):.2f} ms")
        print(f"P95 Latency: {np.percentile(latencies, 95):.2f} ms")
        print(f"QPS: {qps:.2f}")

    if __name__ == "__main__":
        benchmark()
    ```

3.  **Run Benchmark**:
    ```bash
    python3 benchmark.py
    ```

## Cleanup

When finished, delete the cluster to avoid charges.

```bash
gcloud alloydb clusters delete ${CLUSTER_ID} --region=${REGION} --force --project=${PROJECT_ID}
```

## References

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
*   [FlagEmbedding (GitHub)](https://github.com/FlagOpen/FlagEmbedding)
*   [Marqo/marqo-GS-10M (Hugging Face)](https://huggingface.co/datasets/Marqo/marqo-GS-10M)
*   [Grant IAM permissions for Vertex AI](https://docs.cloud.google.com/alloydb/docs/ai/configure-vertex-ai#grant-iam-permissions)
