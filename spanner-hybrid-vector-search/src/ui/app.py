import os
import vertexai
from vertexai.generative_models import GenerativeModel
from flask import Flask, render_template, request, jsonify
from google.cloud import spanner

app = Flask(__name__)

# Initialize Spanner Client
project_id = os.environ.get("PROJECT_ID")
instance_id = os.environ.get("SPANNER_INSTANCE")
database_id = os.environ.get("SPANNER_DATABASE")
location = os.environ.get("LOCATION", "global") # Default to global for Gemini 3 Preview

if not all([project_id, instance_id, database_id]):
    print("Warning: usage requires PROJECT_ID, SPANNER_INSTANCE, and SPANNER_DATABASE env vars.")

# Initialize Vertex AI
if project_id:
    vertexai.init(project=project_id, location=location)
    # Initialize Gemini Model
    # usage: gemini-3-flash-preview or gemini-1.5-pro
    chat_model = GenerativeModel("gemini-3-flash-preview")

spanner_client = spanner.Client(project=project_id)
instance = spanner_client.instance(instance_id)
database = instance.database(database_id)

def execute_search(query, filters=None):
    """
    Executes Hybrid Search logic and returns valid rows.
    filters: dict with keys year, make, model, engine
    """
    if not filters:
        filters = {}

    year = filters.get("year")
    make = filters.get("make")
    model = filters.get("model")
    engine = filters.get("engine")

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
    ),
    merged AS (
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
    )
    SELECT
      MAX(rrf_score) AS rrf_score,
      ANY_VALUE(id) AS id,
      ANY_VALUE(TextContent) AS TextContent,
      SourceUri,
      ChunkIndex,
      ANY_VALUE(Year) AS Year,
      ANY_VALUE(Make) AS Make,
      ANY_VALUE(Model) AS Model,
      ANY_VALUE(Engine) AS Engine,
      ANY_VALUE(Metadata) AS Metadata
    FROM merged
    GROUP BY SourceUri, ChunkIndex
    ORDER BY rrf_score DESC
    LIMIT 50;
    """

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
        
        data = []
        for row in results:
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
                "metadata": row[9]
            }
            data.append(item)
        return data

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search")
def search():
    query = request.args.get("q")
    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    filters = {
        "year": request.args.get("year"),
        "make": request.args.get("make"),
        "model": request.args.get("model"),
        "engine": request.args.get("engine")
    }

    try:
        data = execute_search(query, filters)
        return jsonify(data)
    except Exception as e:
        print(f"Error executing query: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/chat", methods=["POST"])
def chat():
    from urllib.parse import quote

    data = request.json
    message = data.get("message")
    if not message:
        return jsonify({"error": "Missing message"}), 400

    try:
        # Step 1: Search for grounding
        search_results = execute_search(message)[:20]

        # Step 2: Format context
        context_str = ""
        for i, item in enumerate(search_results):
            # Construct View URL with Highlighting
            # 1. Base URL
            source_uri = item.get('source_uri', '') or ''
            view_url = source_uri.replace('gs://', 'https://storage.cloud.google.com/')
            
            # 2. Page & Text Fragment
            page_num = item.get("metadata", {}).get("page_number")
            text_content = (item.get("text_content") or "").strip()
            
            fragments = []
            if page_num and source_uri.lower().endswith('.pdf'):
                fragments.append(f"page={page_num}")
            
            if text_content:
                # Basic quoting for text fragment
                safe_text = quote(text_content)
                fragments.append(f"text={safe_text}")
                
            if fragments:
                # text fragment syntax: #:~:text=...
                # page syntax: #page=N
                # Combined: #page=N&text=... ? No, Chrome uses #:~:text=
                # PDF uses #page=N
                # To combine: #page=N:~:text=... works in Chrome?
                # Actually, PDF viewer might not support :~:text= highlight ON TOP of page param easily.
                # But let's try appending.
                # If both: url#page=N:~:text=...
                
                # Check if we have page
                # If PDF: use #page=N first.
                # Then :~:text=
                anchor = ""
                if page_num and source_uri.lower().endswith('.pdf'):
                    anchor += f"page={page_num}"
                
                if text_content:
                    anchor += f":~:text={quote(text_content)}"
                
                view_url += f"#{anchor}"

            
            ref_id = i + 1
            filename = source_uri.split('/')[-1]
            
            context_str += f"Source {ref_id}:\n"
            context_str += f"Title: {filename}\n"
            if page_num:
                context_str += f"Page: {page_num}\n"
            context_str += f"Content: {text_content}\n"
            context_str += f"Link: {view_url}\n\n"

        # Step 3: Prompt Gemini
        prompt = f"""
You are a helpful assistant for vehicle maintenance.
Answer the user's question using ONLY the provided context.
If the answer is not in the context, say "I don't know based on the provided documents."

Context:
{context_str}

Question: {message}

Instructions:
- Cite your sources using the format [Document Title](Link).
- Use the provided "Link" URL exactly as is for the citation.
- Keep the answer concise and helpful.
"""
        response = chat_model.generate_content(prompt)
        answer = response.text

        return jsonify({
            "answer": answer,
            "grounding": search_results
        })

    except Exception as e:
        print(f"Error in chat: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
