# Spanner Vector Search Demo

This project deploys a serverless pipeline to ingest PDF, HTML, and XML documents, chunk them, generate embeddings using Vertex AI (Gemini), and store them in Google Cloud Spanner for vector search and hybrid vector + fulltext search.

## Architecture

1. **GCS Bucket**: Input drop zone for documents.
2. **Eventarc**: Triggers Cloud Function on new file upload.
3. **Cloud Function (Python)**:
    - **Metadata Extraction**:
        - **Regex Priority**: Attempts to extract `Year` and `Model` from the filename using regex (Format: `YYYY-Model-...`).
        - **Gemini Extraction**: Uses **Gemini 3 Flash Preview** (Location: `global`) with **Structured Output** to extract `Make`, `Engine`, and fallback `Year`/`Model` if regex fails.
    - **Chunking**:
        - Uses **Document AI** (OCR) for PDF files.
        - Uses **BeautifulSoup** for HTML files.
        - Uses standard iter parsing for XML files.
    - **Embedding Generation**:
        - Uses **Vertex AI gemini-embedding-001** (Location: `us-central1`) to generate vector embeddings for each chunk.
    - **Spanner Storage**:
        - Writes the chunks, their embeddings, and the refined metadata (Gemini + Fallback) to Spanner.
        - **Vector Search**:
            - The `Documents` table includes an **Embedding** column defined as `ARRAY<FLOAT64>`.
            - This stores the vector representation of the chunk text, enabling semantic similarity search using `COSINE_DISTANCE`.
        - **Full-Text Search**:
            - The `Documents` table includes a **ChunkTokens** column defined as `TOKENLIST AS (TOKENIZE_FULLTEXT(TextContent)) HIDDEN`.
            - This automatically tokenizes the text content for keyword search, enabling the hybrid search capabilities (combining Vector + FTS).
4. **Spanner**: Stores the vectors and metadata for hybrid search.

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
  WITH vector AS (
    SELECT embeddings.values FROM ML.PREDICT(
      MODEL EmbeddingsModel, (
        SELECT "<NATURAL LANGUAGE QUERY>" AS content)
  ))
  SELECT * EXCEPT(Embedding, values)
  FROM Documents, vector
  ORDER BY COSINE_DISTANCE(embedding, vector.values)
  LIMIT 200;  
   ```

2. **Full-Text Search** (Keyword Matching):
   ```sql
   SELECT * EXCEPT(Embedding)
   FROM Documents
   WHERE SEARCH(ChunkTokens, '<NATURAL LANGUAGE QUERY>')
   ORDER BY SCORE(ChunkTokens, '<NATURAL LANGUAGE QUERY>') DESC
   LIMIT 200;
   ```

3. **Hybrid Search** (Vector + Full-Text using Reciprocal Rank Fusion):
   ```sql
   @{optimizer_version=7}
  WITH vector AS (
    SELECT embeddings.values FROM ML.PREDICT(
      MODEL EmbeddingsModel, (
        SELECT "<NATURAL LANGUAGE QUERY>" AS content)
  )),
  knn AS (
    SELECT rank, x.*
    FROM UNNEST(ARRAY(
      SELECT AS STRUCT 
        id, TextContent, SourceUri, ChunkIndex, 
        Year, Make, Model, Engine, Metadata
      FROM Documents, vector
      ORDER BY COSINE_DISTANCE(vector.values, embedding)
      LIMIT 200)) AS x WITH OFFSET AS rank
  ),
  fts AS (
    SELECT rank, x.*
    FROM UNNEST(ARRAY(
      SELECT AS STRUCT 
        id, TextContent, SourceUri, ChunkIndex, 
        Year, Make, Model, Engine, Metadata
      FROM Documents
      WHERE SEARCH(ChunkTokens, '<NATURAL LANGUAGE QUERY>')
      ORDER BY SCORE(ChunkTokens, '<NATURAL LANGUAGE QUERY>') DESC
      LIMIT 200)) AS x WITH OFFSET AS rank
  )
  -- RRF logic to merge Vector and Full-Text results
  SELECT 
    SUM(1 / (60 + rank)) AS rrf_score,
    id,
    ANY_VALUE(TextContent) AS TextContent,
    ANY_VALUE(SourceUri) AS SourceUri,
    ANY_VALUE(ChunkIndex) AS ChunkIndex,
    ANY_VALUE(Year) AS Year,
    ANY_VALUE(Make) AS Make,
    ANY_VALUE(Model) AS Model,
    ANY_VALUE(Engine) AS Engine,
    ANY_VALUE(Metadata) AS Metadata
  FROM (
    SELECT * FROM knn
    UNION ALL
    SELECT * FROM fts
  )
  GROUP BY id
  ORDER BY rrf_score DESC
  LIMIT 50;
   ```
   *(Note: RRF constant `60` is standard, adjustable based on preference).*

## Cleanup
To destroy all resources:
```bash
terraform destroy -var="project_id=YOUR_PROJECT_ID"
```
