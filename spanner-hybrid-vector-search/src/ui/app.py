import os
from flask import Flask, render_template, request, jsonify
from google.cloud import spanner

app = Flask(__name__)

# Initialize Spanner Client
project_id = os.environ.get("PROJECT_ID")
instance_id = os.environ.get("SPANNER_INSTANCE")
database_id = os.environ.get("SPANNER_DATABASE")

if not all([project_id, instance_id, database_id]):
    # Fallback for local testing if env vars not set (optional, or just warn)
    print("Warning: usage requires PROJECT_ID, SPANNER_INSTANCE, and SPANNER_DATABASE env vars.")

spanner_client = spanner.Client(project=project_id)
instance = spanner_client.instance(instance_id)
database = instance.database(database_id)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search")
def search():
    query = request.args.get("q")
    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    year = request.args.get("year")
    make = request.args.get("make")
    model = request.args.get("model")
    engine = request.args.get("engine")

    # The exact query provided by user
    sql = """
    @{optimizer_version=7}
    WITH vector AS (
      SELECT embeddings.values FROM ML.PREDICT(
        MODEL EmbeddingsModel, (
          SELECT @query AS content)
    )),
    knn AS (
      SELECT rank, x.*
      FROM UNNEST(ARRAY(
        SELECT AS STRUCT 
          id, TextContent, SourceUri, ChunkIndex, 
          Year, Make, Model, Engine, Metadata
        FROM Documents, vector
        WHERE Embedding IS NOT NULL
          AND (@year IS NULL OR Year = @year)
          AND (@make IS NULL OR Make = @make)
          AND (@model IS NULL OR Model = @model)
          AND (@engine IS NULL OR Engine = @engine)
        ORDER BY APPROX_COSINE_DISTANCE(vector.values, Embedding, options => JSON'{"num_leaves_to_search": 10}')
        LIMIT 200)) AS x WITH OFFSET AS rank
    ),
    fts AS (
      SELECT rank, x.*
      FROM UNNEST(ARRAY(
        SELECT AS STRUCT 
          id, TextContent, SourceUri, ChunkIndex, 
          Year, Make, Model, Engine, Metadata
        FROM Documents
        WHERE SEARCH(ChunkTokens, @query)
          AND (@year IS NULL OR Year = @year)
          AND (@make IS NULL OR Make = @make)
          AND (@model IS NULL OR Model = @model)
          AND (@engine IS NULL OR Engine = @engine)
        ORDER BY SCORE(ChunkTokens, @query) DESC
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
    """

    try:
        with database.snapshot() as snapshot:
            params = {
                "query": query,
                "year": year,
                "make": make,
                "model": model,
                "engine": engine
            }
            param_types = {
                "query": spanner.param_types.STRING,
                "year": spanner.param_types.STRING,
                "make": spanner.param_types.STRING,
                "model": spanner.param_types.STRING,
                "engine": spanner.param_types.STRING
            }
            
            results = snapshot.execute_sql(
                sql,
                params=params,
                param_types=param_types
            )
            
            # Serialize results
            data = []
            for row in results:
                # Provide a helper to construct a GCS Link or similar if needed
                # For now just passing raw data
                item = {
                    "rrf_score": row[0],
                    "id": row[1],
                    "text_content": row[2],
                    "source_uri": row[3],
                    "chunk_index": row[4],
                    "year": row[5],
                    "make": row[6],
                    "model": row[7],
                    "engine": row[8],
                    "metadata": row[9] # This might be a generic object, handle carefully
                }
                data.append(item)
                
            return jsonify(data)

    except Exception as e:
        print(f"Error executing query: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
