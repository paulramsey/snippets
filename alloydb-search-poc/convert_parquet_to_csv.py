#!/usr/bin/env python3
import sys
import os
import pandas as pd



def convert_parquet_to_csv(input_file, output_file, bucket_name=None):
    """
    Converts the Marqo dataset from Parquet to CSV format suitable for AlloyDB bulk import.
    
    Expected CSV columns for import:
    1. product_id
    2. name (mapped from 'title')
    3. description (mapped from 'title' if description missing, or just title again)
    4. category (mapped from 'query')
    5. image_url (mapped from 'image')
    
    The output CSV will NOT have a header row.
    """
    
    print(f"Reading {input_file}...")
    try:
        df = pd.read_parquet(input_file)
        # Deduplicate based on product_id to ensure primary key uniqueness
        initial_count = len(df)
        df.drop_duplicates(subset=['product_id'], keep='first', inplace=True)
        final_count = len(df)
        if initial_count != final_count:
            print(f"Removed {initial_count - final_count} duplicate rows.")
    except Exception as e:
        print(f"Error reading Parquet file: {e}")
        sys.exit(1)
            
    if bucket_name:
        print(f"Uploading images to gs://{bucket_name}/images/...")
        from google.cloud import storage
        import concurrent.futures
        
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        
        # Create local images directory
        os.makedirs("images", exist_ok=True)
        
        def extract_and_upload_image(row):
            try:
                if 'image' not in row or row['image'] is None:
                    return None
                
                image_data = row['image']
                if not isinstance(image_data, dict):
                    return None
                    
                if 'bytes' not in image_data:
                    return None
                    
                image_bytes = image_data['bytes']
                product_id = str(row['product_id'])
                
                # Determine extension
                extension = "jpg" 
                if 'path' in image_data and image_data['path']:
                    ext = os.path.splitext(image_data['path'])[1]
                    if ext:
                        extension = ext.lstrip('.')
                
                filename = f"{product_id}.{extension}"
                local_path = os.path.join("images", filename)
                
                # Write to local file
                with open(local_path, "wb") as f:
                    f.write(image_bytes)
                
                return (local_path, f"images/{filename}")
            except Exception as e:
                print(f"Error extracting image for {row.get('product_id')}: {e}")
                return None

        print("Extracting images locally...")
        # Extract all images first
        # We use a list to keep order corresponding to dataframe
        extraction_results = df.apply(extract_and_upload_image, axis=1)
        
        # Filter out failed extractions for upload
        to_upload = [res for res in extraction_results if res is not None]
        
        print(f"Extracted {len(to_upload)} images. Starting parallel upload...")
        
        def upload_file(paths):
            local_path, blob_name = paths
            try:
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(local_path)
                return f"gs://{bucket_name}/{blob_name}"
            except Exception as e:
                print(f"Error uploading {blob_name}: {e}")
                return None

        # Parallel upload
        # map product_id to GCS URI for easy lookup
        # actually, extraction_results corresponds to df rows, so we can just use the result
        # BUT we need to upload first.
        
        # We'll use a ThreadPoolExecutor
        gcs_uris = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            # We want to maintain order to map back to df
            # extraction_results contains (local_path, blob_name) or None
            
            # Create a map of future -> index
            future_to_index = {}
            for i, res in enumerate(extraction_results):
                if res is not None:
                    future = executor.submit(upload_file, res)
                    future_to_index[future] = i
            
            # Initialize results list with None
            final_uris = [None] * len(df)
            
            # Collect results as they complete
            completed_count = 0
            total_uploads = len(future_to_index)
            
            for future in concurrent.futures.as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    uri = future.result()
                    final_uris[idx] = uri
                    completed_count += 1
                    if completed_count % 100 == 0:
                        print(f"Uploaded {completed_count}/{total_uploads} images...")
                except Exception as exc:
                    print(f"Upload generated an exception: {exc}")
        
        print(f"Parallel upload complete.")
        
        # Update dataframe
        df['image'] = final_uris
        
        # Cleanup local images
        # shutil.rmtree("images") # Optional: clean up
    
    
    print(f"Transforming data ({len(df)} rows)...")
    
    # Select and rename columns
    # We need: product_id, name, description, category, image_url
    
    # create a new dataframe with the desired structure
    output_df = pd.DataFrame()
    output_df['product_id'] = df['product_id']
    output_df['name'] = df['title']
    output_df['description'] = df['title'] # Using title as description since dataset lacks long text
    output_df['category'] = df['query']
    
    # Check if 'image' is a dict (original parquet) or string (if we replaced it)
    # If we didn't upload, we might still have the dict with bytes. 
    # For now, if we didn't upload, we just keep it as is (which might break CSV import if not handled)
    # But the requirement was specifically to upload.
    output_df['image_url'] = df['image']
    
    print(f"Writing to {output_file}...")
    # Write to CSV without header and index
    output_df.to_csv(output_file, index=False, header=False)
    
    print("Conversion complete!")



def download_dataset(repo_id, filename, output_path):
    from huggingface_hub import hf_hub_download
    import shutil
    print(f"Downloading {filename} from {repo_id}...")
    try:
        local_path = hf_hub_download(repo_id=repo_id, filename=filename, repo_type="dataset")
        shutil.copy(local_path, output_path)
        print(f"Download complete: {output_path}")
    except Exception as e:
        print(f"Failed to download file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Default to known small files from the dataset
    DEFAULT_FILENAMES = ["data/in_domain-0.parquet", "data/in_domain-1.parquet"]
    import argparse
    parser = argparse.ArgumentParser(description="Convert Marqo Parquet to CSV for AlloyDB")
    parser.add_argument("input_path", nargs="?", default="marqo_data.parquet", help="Path to input Parquet file")
    parser.add_argument("output_path", nargs="?", default="marqo_subset.csv", help="Path to output CSV file")
    parser.add_argument("--bucket", help="GCS bucket name for image upload")
    
    args = parser.parse_args()
    
    # Check if input file exists, if not download and combine parts
    if not os.path.exists(args.input_path) and args.input_path == "marqo_data.parquet":
        print(f"Input file {args.input_path} not found. Downloading 2 parts from Marqo dataset...")
        
        parts = []
        for i, filename in enumerate(DEFAULT_FILENAMES):
            temp_path = f"temp_part_{i}.parquet"
            download_dataset("Marqo/marqo-GS-10M", filename, temp_path)
            try:
                parts.append(pd.read_parquet(temp_path))
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        
        if parts:
            print("Combining parts...")
            full_df = pd.concat(parts, ignore_index=True)
            full_df.to_parquet(args.input_path)
            print(f"Saved combined data to {args.input_path} ({len(full_df)} rows)")
        else:
            print("No data downloaded.")
            sys.exit(1)
            
    convert_parquet_to_csv(args.input_path, args.output_path, bucket_name=args.bucket)
