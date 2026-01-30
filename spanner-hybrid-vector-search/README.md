# Spanner Vector Search Demo

This project deploys a serverless pipeline to ingest PDF, HTML, and XML documents, chunk them, generate embeddings using Vertex AI (Gemini), and store them in Google Cloud Spanner for vector search and hybrid vector + fulltext search.

## Architecture

1. **GCS Bucket**: Input drop zone for documents.
2. **Eventarc**: Triggers Cloud Function on new file upload.
3. **Cloud Function (Python)**: 
    - Downloads file.
    - Uses **Document AI** (for PDF/HTML) or standard parser (for XML) to chunk text.
    - Generates embeddings using **Vertex AI** (`gemini-embedding-001` or compatible).
    - Writes chunks + embeddings + metadata to **Spanner**.
4. **Spanner**: Stores the vectors and metadata.

## Prerequisites

- Google Cloud Project with Billing Enabled.
- `gcloud` CLI installed and authenticated.
- Terraform installed (>= 1.0).

## Deployment

### 1. Authenticate
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### 2. Deploy Infrastructure
Navigate to the `terraform` directory:
```bash
cd terraform
terraform init
terraform apply -var="region=us-central1" -var="project_id=YOUR_PROJECT_ID"
```
Type `yes` when prompted.

**Note**: The first deployment might take a few minutes as it enables APIs and creates the Spanner instance.

### 3. Usage

#### Upload Documents
Drop a PDF, HTML, or XML file into the created bucket (output as `input_bucket_name` from Terraform):
```bash
gsutil cp my-doc.pdf gs://YOUR_INPUT_BUCKET_NAME/
```

#### Query Spanner

1. **Vector Search** (Semantic Similarity):
   ```sql
   SELECT Id, TextContent, COSINE_DISTANCE(Embedding, @query_vector) as Distance
   FROM Documents
   ORDER BY Distance ASC
   LIMIT 10
   ```

2. **Full-Text Search** (Keyword Matching):
   ```sql
   SELECT Id, TextContent, SCORE(Documents, 'score') as Score
   FROM Documents
   WHERE SEARCH(ChunkTokens, @query_text)
   ORDER BY Score DESC
   LIMIT 10
   ```

3. **Hybrid Search** (Vector + Full-Text using Reciprocal Rank Fusion):
   ```sql
   WITH
     vector_search AS (
       SELECT Id, RANK() OVER (ORDER BY COSINE_DISTANCE(Embedding, @query_vector) ASC) as rank_v
       FROM Documents
       ORDER BY rank_v ASC
       LIMIT 100
     ),
     text_search AS (
       SELECT Id, RANK() OVER (ORDER BY SCORE(Documents, 'score') DESC) as rank_t
       FROM Documents
       WHERE SEARCH(ChunkTokens, @query_text)
       LIMIT 100
     )
   SELECT 
     COALESCE(v.Id, t.Id) as Id,
     (COALESCE(1.0 / (60 + v.rank_v), 0.0) + COALESCE(1.0 / (60 + t.rank_t), 0.0)) as rrf_score
   FROM vector_search v
   FULL OUTER JOIN text_search t ON v.Id = t.Id
   ORDER BY rrf_score DESC
   LIMIT 10
   ```
   *(Note: RRF constant `60` is standard, adjustable based on preference).*

## Cleanup
To destroy all resources:
```bash
terraform destroy -var="project_id=YOUR_PROJECT_ID"
```
