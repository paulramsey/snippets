import os
import re
import uuid
import json
import functions_framework
from google.cloud import spanner
from google.cloud import storage
import vertexai
from vertexai.language_models import TextEmbeddingModel
from chunker import get_chunker
from google.cloud.spanner_v1 import JsonObject

# Initialize clients globally
project_id = os.environ.get("PROJECT_ID")
location = os.environ.get("LOCATION", "us-central1")
docai_location = os.environ.get("DOCAI_LOCATION", "us")
spanner_instance_id = os.environ.get("SPANNER_INSTANCE")
spanner_database_id = os.environ.get("SPANNER_DATABASE")
docai_ocr_processor_id = os.environ.get("DOCAI_OCR_PROCESSOR_ID")

spanner_client = spanner.Client(project=project_id)
instance = spanner_client.instance(spanner_instance_id)
database = instance.database(spanner_database_id)
storage_client = storage.Client(project=project_id)

def clean_metadata(meta):
    import math
    if isinstance(meta, dict):
        return {k: clean_metadata(v) for k, v in meta.items()}
    elif isinstance(meta, list):
        return [clean_metadata(v) for v in meta]
    elif isinstance(meta, float):
        if math.isnan(meta) or math.isinf(meta):
            return 0.0
        return meta
    else:
        return meta

vertexai.init(project=project_id, location=location)
embedding_model = TextEmbeddingModel.from_pretrained("gemini-embedding-001")

@functions_framework.cloud_event
def process_document_event(cloud_event):
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]
    content_type = data.get("contentType", "application/octet-stream")

    print(f"Processing event for file: {file_name} from bucket: {bucket_name}, type: {content_type}")

    if content_type not in ["application/pdf", "text/html", "application/xml", "text/xml"]:
        # Try to infer if missing
        if file_name.endswith(".pdf"): content_type = "application/pdf"
        elif file_name.endswith(".html"): content_type = "text/html"
        elif file_name.endswith(".xml"): content_type = "application/xml"
        else:
            print(f"Skipping unsupported content type: {content_type}")
            return

    # Download file to temp
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    temp_file_path = f"/tmp/{uuid.uuid4()}_{os.path.basename(file_name)}"
    blob.download_to_filename(temp_file_path)

    try:
        process_file(temp_file_path, content_type, f"gs://{bucket_name}/{file_name}")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

def process_file(file_path: str, content_type: str, source_uri: str):
    """
    Processes a local file: chunks it, embeds it, and writes to Spanner.
    """
    print(f"Processing local file: {file_path} with type {content_type}")
    
    # Initialize Spanner client locally to avoid global state issues
    spanner_client = spanner.Client(project=project_id)
    instance = spanner_client.instance(spanner_instance_id)
    database = instance.database(spanner_database_id)
    
    # Determine processor ID
    processor_id = None
    if content_type == "application/pdf":
        processor_id = docai_ocr_processor_id
    
    # Chunk the document
    if processor_id or content_type in ["application/xml", "text/xml", "text/html"]:
        chunker = get_chunker(content_type, project_id, docai_location, processor_id)
        chunks = chunker.chunk(file_path, content_type)
    else:
        print(f"No valid processor found for {content_type}")
        return

    print(f"Generated {len(chunks)} chunks for {source_uri}")

    if not chunks:
        print("No chunks generated.")
        return

    write_embeddings_and_metadata(chunks, source_uri, file_path)

def write_embeddings_and_metadata(chunks, source_uri, file_path):
    # Prepare for Spanner write
    spanner_rows = []
    
    # Batch embedding generation
    batch_size = 10
    import json # Ensure json is imported
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        texts = [c[0] for c in batch]
        
        try:
            embeddings = embedding_model.get_embeddings(texts)
        except Exception as e:
            print(f"Error generating embeddings for batch {i}: {e}")
            continue

        for j, (text, metadata) in enumerate(batch):
            if j >= len(embeddings):
                 break
                 
            embedding_vector = embeddings[j].values
            row_id = str(uuid.uuid4())
            
            # Extract vehicle info
            vehicle_info = extract_vehicle_info(os.path.basename(file_path))
            
            # Clean metadata to remove NaNs/Infs which cause 400 errors
            cleaned_meta = clean_metadata(metadata)

            spanner_rows.append(
                (
                    row_id,
                    source_uri,
                    i + j,
                    text,
                    JsonObject(cleaned_meta),
                    embedding_vector,
                    vehicle_info.get("Year"),
                    vehicle_info.get("Make"),
                    vehicle_info.get("Model"),
                    vehicle_info.get("Engine")
                )
            )

    if spanner_rows:
        with database.batch() as batch:
            batch.insert(
                table="Documents",
                columns=("Id", "SourceUri", "ChunkIndex", "TextContent", "Metadata", "Embedding", "Year", "Make", "Model", "Engine"),
                values=spanner_rows,
            )
        print(f"Successfully wrote {len(spanner_rows)} rows to Spanner.")

def extract_vehicle_info(filename: str) -> dict:
    """
    Extracts Year, Make, Model, Engine from filename using regex conventions.
    Expected format patterns:
    YYYY-Model-... (e.g. 2020-f150...)
    """
    info = {
        "Year": None,
        "Make": None,
        "Model": None,
        "Engine": None
    }
    
    # Simple regex for typical pattern: 2020-f150
    # You can expand this logic as needed based on file naming conventions
    match = re.search(r'(\d{4})[_-]([a-zA-Z0-9]+)', filename)
    if match:
        info["Year"] = match.group(1)
        info["Model"] = match.group(2)
        # Inferred Make if Model is known (demo logic)
        if info["Model"].lower() == "f150":
            info["Make"] = "Ford"
            
    return info
