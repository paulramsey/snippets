resource "google_spanner_instance" "vector_db" {
  name         = "vector-db"
  config       = "regional-${var.region}"
  display_name = "Vector DB Instance"
  num_nodes    = 1
  edition      = "ENTERPRISE"

  depends_on = [google_project_service.services]
}

resource "google_spanner_database" "embeddings_db" {
  instance = google_spanner_instance.vector_db.name
  name     = "embeddings-db"
  ddl = [
    <<-EOF
    CREATE TABLE Documents (
      Id STRING(36) NOT NULL,
      SourceUri STRING(MAX),
      ChunkIndex INT64,
      TextContent STRING(MAX),
      Year STRING(MAX),
      Make STRING(MAX),
      Model STRING(MAX),
      Engine STRING(MAX),
      Metadata JSON,
      ChunkTokens TOKENLIST AS (TOKENIZE_FULLTEXT(TextContent)) HIDDEN,
      Embedding ARRAY<FLOAT64>
    ) PRIMARY KEY (Id)
    EOF

    , <<-EOF
    CREATE MODEL IF NOT EXISTS EmbeddingsModel INPUT(
      content STRING(MAX),
    ) OUTPUT(
      embeddings STRUCT<statistics STRUCT<truncated BOOL, token_count FLOAT64>, values ARRAY<FLOAT64>>,
    ) REMOTE OPTIONS (
      endpoint = '//aiplatform.googleapis.com/projects/${var.project_id}/locations/us-central1/publishers/google/models/gemini-embedding-001'
    )
    EOF

    , <<-EOF
    CREATE SEARCH INDEX chunk_tokens_idx
    ON Documents(ChunkTokens)
    OPTIONS (sort_order_sharding = true)
    EOF
  ]
  deletion_protection = false # For easy teardown in demo
}
