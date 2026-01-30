import os
import re
import uuid
import json
import functions_framework
from google.cloud import spanner
from google.cloud import storage
import vertexai
from vertexai.language_models import TextEmbeddingModel
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from chunker import get_chunker
from google.cloud.spanner_v1 import JsonObject

# Initialize clients globally
project_id = os.environ.get("PROJECT_ID")
location = os.environ.get("LOCATION", "global")
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

# Initialize Embedding Model in us-central1 (required for this model)
vertexai.init(project=project_id, location="us-central1")
embedding_model = TextEmbeddingModel.from_pretrained("gemini-embedding-001")

# Initialize Gemini 3 Flash Preview in global
# We explicitly force global here because the model is a preview model and might not be available in regional endpoints like us-central1 yet.
# The LOCATION env var in Cloud Functions is often set to the function's region (us-central1), which breaks this.
vertexai.init(project=project_id, location="global")
metadata_model = GenerativeModel("gemini-3-flash-preview")

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
    
    # Extract vehicle info once per file
    vehicle_info = extract_vehicle_info(file_path, content_type)
    print(f"Extracted vehicle info: {vehicle_info}")

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

    write_embeddings_and_metadata(chunks, source_uri, file_path, vehicle_info)

def write_embeddings_and_metadata(chunks, source_uri, file_path, vehicle_info):
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
                    vehicle_info.get("year"),
                    vehicle_info.get("make"),
                    vehicle_info.get("model"),
                    vehicle_info.get("engine")
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

def extract_vehicle_info(file_path: str, content_type: str) -> dict:
    """
    Extracts Year, Make, Model, Engine from the document using Gemini 3 Flash Preview.
    Returns null for values that can't be determined with high confidence.
    """
    print(f"Extracting metadata using Gemini 3 Flash Preview for {file_path}")
    
    prompt = """
    Extract the vehicle year, make, model, and engine from this document.
    Return null for values that can't be determined with high confidence.
    """
    
    vehicle_schema = {
        "type": "OBJECT",
        "properties": {
            "year": {"type": "INTEGER", "nullable": True},
            "make": {"type": "STRING", "nullable": True},
            "model": {"type": "STRING", "nullable": True},
            "engine": {"type": "STRING", "nullable": True}
        },
        "required": ["year", "make", "model", "engine"]
    }
    
    generation_config = GenerationConfig(
        response_mime_type="application/json",
        response_schema=vehicle_schema
    )

    # Priority 1: Regex from filename for Year and Model
    filename = os.path.basename(file_path)
    regex_metadata = {"year": None, "model": None}
    
    # Regex to capture Year (first) and Model (second) separated by hyphen/underscore
    # e.g., 2020-f150-...
    match = re.search(r'^(\d{4})[_-]([a-zA-Z0-9]+)', filename)
    if match:
        try:
            regex_metadata["year"] = int(match.group(1))
            regex_metadata["model"] = match.group(2)
            print(f"Regex extracted Year: {regex_metadata['year']}, Model: {regex_metadata['model']} from {filename}")
        except ValueError:
            pass

    # Priority 2: Gemini for Make, Engine, and fallback for Year/Model
    gemini_metadata = {"year": None, "make": None, "model": None, "engine": None}
    try:
        with open(file_path, "rb") as f:
            data = f.read()
            
        parts = [Part.from_data(data=data, mime_type=content_type), prompt]
        
        response = metadata_model.generate_content(
            parts,
            generation_config=generation_config
        )
        
        gemini_metadata = json.loads(response.text)
    except Exception as e:
        print(f"Error calling Gemini for metadata extraction: {e}")

    # Merge: Regex overrides Gemini for Year/Model
    final_result = gemini_metadata.copy()
    
    if regex_metadata["year"]:
        final_result["year"] = regex_metadata["year"]
        
    if regex_metadata["model"]:
        final_result["model"] = regex_metadata["model"]

    return final_result

