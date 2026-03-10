import time
import psycopg2
import numpy as np
import threading
import argparse
import sys

# Database Configuration
DB_HOST = "10.32.0.13" 
DB_USER = "postgres"
DB_PASS = "SuperSecretPassword@123"
DB_NAME = "postgres"

# Mapping of search types to their database column and model ID
SEARCH_CONFIG = {
    "gemini": {
        "column": "embedding",
        "model_id": "gemini-embedding-001"
    },
    "bge": {
        "column": "embedding_bge",
        "model_id": "bge-m3"
    }
}

# Global list to store latencies from all threads
latencies = []
latency_lock = threading.Lock()

def get_connection():
    return psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, dbname=DB_NAME)

def worker(num_queries, search_type):
    config = SEARCH_CONFIG[search_type]
    column = config["column"]
    model_id = config["model_id"]
    
    conn = get_connection()
    cur = conn.cursor()
    
    # 1. Get a dummy vector first to use in PREPARE
    cur.execute(f"SELECT embedding('{model_id}', 'performance test')::vector")
    query_vector = cur.fetchone()[0]
    
    # 2. Prepare the statement
    cur.execute(f"PREPARE search_plan (vector) AS SELECT product_id FROM product ORDER BY {column} <=> $1 LIMIT 100")
    
    local_latencies = []
    
    for _ in range(num_queries):
        start = time.time()
        cur.execute("EXECUTE search_plan (%s)", (query_vector,))
        cur.fetchall()
        lat = (time.time() - start) * 1000 # ms
        local_latencies.append(lat)
        
    cur.close()
    conn.close()
    
    with latency_lock:
        latencies.extend(local_latencies)

def benchmark(search_type, total_requests=1000, concurrency=10):
    print(f"Starting {search_type} benchmark: {total_requests} requests, {concurrency} threads...")
    
    threads = []
    queries_per_thread = total_requests // concurrency
    
    start_time = time.time()
    
    for _ in range(concurrency):
        t = threading.Thread(target=worker, args=(queries_per_thread, search_type))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()

    total_time = time.time() - start_time
    qps = total_requests / total_time
    
    print(f"Model: {search_type} ({SEARCH_CONFIG[search_type]['model_id']})")
    print(f"P50 Latency: {np.percentile(latencies, 50):.2f} ms")
    print(f"P95 Latency: {np.percentile(latencies, 95):.2f} ms")
    print(f"QPS: {qps:.2f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AlloyDB Vector Search Benchmark")
    parser.add_argument("--type", choices=["gemini", "bge"], default="gemini", help="Type of embedding to benchmark")
    parser.add_argument("--requests", type=int, default=1000, help="Total number of requests")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of concurrent threads")
    
    args = parser.parse_args()
    
    benchmark(args.type, args.requests, args.concurrency)
