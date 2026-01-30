import os
import sys
import mimetypes
import subprocess
import json
import glob

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

def get_terraform_outputs():
    try:
        # relative path to terraform dir
        tf_dir = os.path.join(os.path.dirname(__file__), '../terraform')
        if not os.path.exists(tf_dir):
            return {}
        
        output = subprocess.check_output(['terraform', 'output', '-json'], cwd=tf_dir)
        return json.loads(output)
    except Exception as e:
        print(f"Could not load terraform outputs: {e}")
        return {}

def main():
    # Load environment variables from Terraform if available
    outputs = get_terraform_outputs()
    
    # helper to safely get value from tf output format {"value": "..."}
    def get_val(key):
        return outputs.get(key, {}).get('value')

    # Set env vars if not already set
    if not os.environ.get("PROJECT_ID") and get_val('project_id'): # Terraform output might not have project_id if we didn't output it
        # Actually we didn't output project_id in outputs.tf, checking if we can get it from gcloud or let user set it.
        pass
    
    # We need to ensure these are set. 
    # If Terraform was applied, we can try to extract from outputs.tf if we actually outputted them.
    # We outputted: input_bucket_name, spanner_instance, spanner_database, function_name.
    # We MISSING: project_id (usually known), location (usually us-central1), docai_processor_id.
    
    if not os.environ.get("SPANNER_INSTANCE") and get_val('spanner_instance'):
        os.environ["SPANNER_INSTANCE"] = get_val('spanner_instance')
        
    if not os.environ.get("SPANNER_DATABASE") and get_val('spanner_database'):
        os.environ["SPANNER_DATABASE"] = get_val('spanner_database')

    if not os.environ.get("SPANNER_DATABASE") and get_val('spanner_database'):
        os.environ["SPANNER_DATABASE"] = get_val('spanner_database')

    if not os.environ.get("DOCAI_OCR_PROCESSOR_ID"):
        if get_val('docai_ocr_processor_id'):
             os.environ["DOCAI_OCR_PROCESSOR_ID"] = get_val('docai_ocr_processor_id')
        else:
             print("WARNING: DOCAI_OCR_PROCESSOR_ID not found in output.")

    # For Project ID, try to get from gcloud if not set
    if not os.environ.get("PROJECT_ID"):
        try:
            p_id = subprocess.check_output(['gcloud', 'config', 'get-value', 'project'], text=True).strip()
            if p_id:
                os.environ["PROJECT_ID"] = p_id
        except:
            print("WARNING: PROJECT_ID not found in env or gcloud config.")

    # For DocAI, we didn't output it. We might fail if it's needed for PDF/HTML.
    # We can try to find it via API or just warn.
    if not os.environ.get("DOCAI_PROCESSOR_ID"):
         # Try to list processors? Or assume user sets it.
         # For now, let's just proceed. If chunker fails, it fails.
         print("INFO: DOCAI_PROCESSOR_ID not set. PDF/HTML processing might fail.")

    print("Environment:")
    print(f"PROJECT_ID: {os.environ.get('PROJECT_ID')}")
    print(f"SPANNER_INSTANCE: {os.environ.get('SPANNER_INSTANCE')}")
    print(f"SPANNER_DATABASE: {os.environ.get('SPANNER_DATABASE')}")

    # Import main AFTER setting env vars (though some globals init immediately, we can patch specific ones)
    import main
    from main import process_file

    # Mock Spanner if credentials/resources are missing to allow testing chunking/embedding only
    if not os.environ.get("SPANNER_INSTANCE") or not os.environ.get("SPANNER_DATABASE"):
        print("\nWARNING: Spanner configuration missing. Mocking Spanner DB for Dry Run.")
        class MockDatabase:
            def run_in_transaction(self, func):
                print("  [MOCK] Spanner Transaction Started")
                # Create a mock transaction object to pass to the function
                class MockTransaction:
                    def insert_or_update(self, table, columns, values):
                        print(f"  [MOCK] Writing {len(values)} rows to {table}")
                        # print first row sample
                        if values:
                            print(f"  [MOCK] Sample Row: {values[0][0]} | {values[0][3][:30]}... | Embedding Len: {len(values[0][5])}")
                
                func(MockTransaction())
                print("  [MOCK] Spanner Transaction Committed")

        main.database = MockDatabase()
        main.instance = "MockInstance"

    docs_dir = os.path.join(os.path.dirname(__file__), '../test-docs')
    files = glob.glob(os.path.join(docs_dir, '*'))
    
    print(f"Found {len(files)} files in {docs_dir}")

    for f in files:
        mime_type, _ = mimetypes.guess_type(f)
        if not mime_type:
            # simple fallback
            if f.endswith('.xml'): mime_type = 'application/xml'
            elif f.endswith('.pdf'): mime_type = 'application/pdf'
            elif f.endswith('.html'): mime_type = 'text/html'
            else: mime_type = 'application/octet-stream'
        
        print(f"\n--- Testing {os.path.basename(f)} ({mime_type}) ---")
        try:
            process_file(f, mime_type, f"local_test://{os.path.basename(f)}")
        except Exception as e:
            print(f"FAILED: {e}")

    # Unit test for vehicle info extraction
    from main import extract_vehicle_info
    print("\n--- Testing extract_vehicle_info ---")
    test_filenames = [
        "2020-f150-manual.pdf",
        "2021-RAM1500-guide.pdf",
        "unknown_file.pdf"
    ]
    for name in test_filenames:
        info = extract_vehicle_info(name)
        print(f"{name} -> {info}")

if __name__ == "__main__":
    main()
