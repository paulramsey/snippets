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


# Create Primary Instance (16 vCPU C4A Machine type)
# Enabling public-ip for easier access
# REQUIRED: Set flags for auto-embeddings and ML integration
gcloud alloydb instances create ${INSTANCE_ID} \
  --cluster=${CLUSTER_ID} \
  --region=${REGION} \
  --cpu-count=16 \
  --machine-type=c4a-highmem-16 \
  --assign-ip \
  --ssl-mode=ALLOW_UNENCRYPTED_AND_ENCRYPTED \
  --database-flags=google_ml_integration.enable_model_support=on,google_ml_integration.enable_faster_embedding_generation=on,scann.enable_zero_knob_index_creation=on \
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
CREATE EXTENSION IF NOT EXISTS alloydb_scann;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;
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

### 3. Configure and Initialize Auto Embeddings
Create a table and configure automatic embedding generation. Unlike `GENERATED ALWAYS AS`, this method uses background processes to manage embeddings efficiently.

```sql
CREATE TABLE product (
  id INT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  category VARCHAR(255),
  color VARCHAR(255),
  -- Column for embeddings (initially NULL, populated by auto-embeddings)
  embedding vector(3072) DEFAULT NULL
);

-- Insert data (embedding column is left NULL)
INSERT INTO product (id, name, description, category, color) VALUES
(1, 'Stuffed Elephant', 'Soft plush elephant with floppy ears.', 'Plush Toys', 'Gray'),
(2, 'Remote Control Airplane', 'Easy-to-fly remote control airplane.', 'Vehicles', 'Red'),
(3, 'Wooden Train Set', 'Classic wooden train set with tracks and trains.', 'Vehicles', 'Multicolor'),
(4, 'Kids Tool Set', 'Toy tool set with realistic tools.', 'Pretend Play', 'Multicolor'),
(5, 'Play Food Set', 'Set of realistic play food items.', 'Pretend Play', 'Multicolor'),
(6, 'Magnetic Tiles', 'Set of colorful magnetic tiles for building.', 'Construction Toys', 'Multicolor'),
(7, 'Kids Microscope', 'Microscope for kids with different magnification levels.', 'Educational Toys', 'White'),
(8, 'Telescope for Kids', 'Telescope designed for kids to explore the night sky.', 'Educational Toys', 'Blue'),
(9, 'Coding Robot', 'Robot that teaches kids basic coding concepts.', 'Educational Toys', 'White'),
(10, 'Kids Camera', 'Durable camera for kids to take pictures and videos.', 'Electronics', 'Pink');

-- Configure and Initialize Auto Embeddings
-- This tells AlloyDB to automatically generate embeddings for the 'description' column
-- using the 'gemini-embedding-001' model and store them in the 'embedding' column.
SELECT ai.initialize_embeddings(
  model_id => 'gemini-embedding-001',
  table_name => 'product',
  content_column => 'description',
  embedding_column => 'embedding',
  batch_size => 50 -- Optional hint
);

-- Check progress (optional)
SELECT * FROM google_ml.embed_gen_progress;

```

### 4. Insert Inventory Data
Create an inventory table for joins (optional, but good for demonstrating filtered search):

```sql
CREATE TABLE product_inventory (
  id INT PRIMARY KEY,
  product_id INT REFERENCES product(id),
  inventory INT,
  price DECIMAL(10,2)
);

INSERT INTO product_inventory (id, product_id, inventory, price) VALUES
(1, 1, 9, 13.09),
(2, 2, 5, 45.99),
(3, 3, 12, 29.99),
(4, 4, 8, 19.99),
(5, 5, 15, 15.99);
```

### 5. Create Auto ScaNN Index
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

### 6. Perform Vector Search
Find products similar to "music" (semantic search).

```sql
-- Simple Vector Search
SELECT id, name, description 
FROM product 
ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector 
LIMIT 3;
```

Find cheapest products similar to "music" (Filtered Search):

```sql
-- Vector Search with Filters and Joins
SELECT p.name, p.description, pi.price
FROM product p 
JOIN product_inventory pi ON p.id = pi.product_id 
WHERE pi.price < 30.00 
ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector 
LIMIT 3;
```

### 7. Perform Hybrid Search
Enhance your search by combining vector similarity with traditional keyword-based scoring using weighted Full-Text Search (FTS).

#### Create Weighted Full-text Search Column
Columns are assigned weights (A=Highest, D=Lowest). We'll prioritize `name` (A), `category` (B), `description` (D).

```sql
ALTER TABLE product ADD COLUMN fts_document tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
  setweight(to_tsvector('english', coalesce(category, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(description, '')), 'D')
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
  SELECT id,
         RANK () OVER (ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector) AS rank
  FROM product
  ORDER BY embedding <=> embedding('gemini-embedding-001', 'music')::vector
  LIMIT 20
),
text_search AS (
  SELECT id,
         RANK () OVER (ORDER BY ts_rank(fts_document, to_tsquery('english', 'music')) DESC) AS rank
  FROM product
  WHERE fts_document @@ to_tsquery('english', 'music')
  ORDER BY ts_rank(fts_document, to_tsquery('english', 'music')) DESC
  LIMIT 20
)
SELECT COALESCE(v.id, t.id) AS id,
       COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score
FROM vector_search v
FULL OUTER JOIN text_search t ON v.id = t.id
ORDER BY rrf_score DESC
LIMIT 5;
```

### 8. Perform Reranking (Vertex AI)
Re-rank the top predictions using the Vertex AI Ranking API for higher precision. This is a "RAG" (Retrieval Augmented Generation) pattern where you retrieve a larger set (e.g., 20) using fast vector search, and then use a heavier model to re-rank the top results.

**Note:** Ensure you have the `semantic-ranker-512@latest` model enabled in Vertex AI if needed, though typically standard models work out of the box with the API.

```sql
-- Reranking Example
WITH initial_retrieval AS (
  -- 1. Retrieve top 10 candidates using fast vector search
  SELECT id, name, description,
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
SELECT p.name, p.description, r.score AS rerank_score
FROM initial_retrieval p
JOIN reranked_results r ON p.rank_id = r.index
ORDER BY r.score DESC;
```

### 9. Bring Your Own Model (BYOM)
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
SELECT name, description, 1 - (embedding <=> embedding('gemini-embedding-001', 'music')::vector) as score
FROM product
ORDER BY score DESC LIMIT 3;

-- 2. BGE-M3 Embedding
SELECT name, description, 1 - (embedding_bge <=> embedding('bge-m3', 'music')::vector) as score
FROM product
ORDER BY score DESC LIMIT 3;

-- 3. Reranking Top 10 with BGE-Reranker
WITH candidates AS (
  SELECT id, name, description
  FROM product
  ORDER BY embedding_bge <=> embedding('bge-m3', 'music')::vector
  LIMIT 10
)
SELECT p.name, p.description, r.score
FROM ai.rank(
  model_id => 'bge-reranker-v2-m3',
  search_string => 'music',
  documents => (SELECT ARRAY_AGG(description) FROM candidates),
  top_n => 3
) r
JOIN candidates p ON r.index = (SELECT row_number() OVER () FROM candidates c WHERE c.id = p.id); -- Note: Simplified join logic for demo
```

```

### 10. Fine-Tune Your Models (Optional)
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
Once trained, upload your model to Hugging Face to deploy it using the steps in **Part 9**.

```bash
pip install huggingface_hub
huggingface-cli login

# Upload Embeddings Model
huggingface-cli upload your-username/bge-m3-custom ./bge-m3-finetuned

# Upload Reranker Model
huggingface-cli upload your-username/bge-reranker-custom ./bge-reranker-finetuned
```

**Deploy:** Update the `MODEL_ID` in **Part 9** to `your-username/bge-m3-custom` or `your-username/bge-reranker-custom`.

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
*   [Run a hybrid vector similarity search](https://docs.cloud.google.com/alloydb/docs/ai/run-hybrid-vector-similarity-search)
*   [Hybrid Search Example (GitHub)](https://github.com/paulramsey/stylesearch-alloydb-ai-demo/blob/main/cymbal_shops_hybrid_search_alloydb_data_prep.ipynb)
*   [Rank and rerank search results](https://docs.cloud.google.com/alloydb/docs/ai/rank-rerank-search-results-rag)
*   [Vertex AI Ranking API (Agent Builder)](https://docs.cloud.google.com/generative-ai-app-builder/docs/ranking)
*   [Register and call remote AI models](https://docs.cloud.google.com/alloydb/docs/ai/register-model-endpoint)
*   [BAAI/bge-m3 (Hugging Face)](https://huggingface.co/BAAI/bge-m3)
*   [BAAI/bge-reranker-v2-m3 (Hugging Face)](https://huggingface.co/BAAI/bge-reranker-v2-m3)
*   [FlagEmbedding (GitHub)](https://github.com/FlagOpen/FlagEmbedding)
*   [Grant IAM permissions for Vertex AI](https://docs.cloud.google.com/alloydb/docs/ai/configure-vertex-ai#grant-iam-permissions)
