# AlloyDB ScaNN ExtensionVersion Upgrade

This document demonstrates the process of upgrading the `alloydb_scann` and `vector` extensions in AlloyDB. It covers verifying the upgrade with a test query, optionally rebuilding the index online, and optionally renaming the index to its original name for ease of use and query hinting.

This procedure uses the test dataset deployed via [https://github.com/paulramsey/stylesearch-alloydb-ai-demo](https://github.com/paulramsey/stylesearch-alloydb-ai-demo).

# Before Update

## Test Query

This test query is used throughout this document to test ScaNN index upgrade and rebuild.

```sql
WITH  
  e AS (  
    SELECT  
      embedding ('gemini-embedding-001', 'Handbag')::vector AS query_embedding  
  ),  
  vector_search AS (  
    SELECT  
      p.id,  
      p.product_embedding <=> e.query_embedding AS distance  
    FROM  
      products p,  
      e  
    WHERE  
      p.product_embedding <=> e.query_embedding < 0.5  
    ORDER BY  
      distance  
    LIMIT  
      50  
  )  
SELECT  
  vs.distance,  
  p.name,  
  p.product_image_uri,  
  p.brand,  
  p.product_description,  
  p.category,  
  p.department,  
  p.cost,  
  p.retail_price::MONEY,  
  p.sku,  
  'VECTOR' AS retrieval_method  
FROM  
  vector_search vs  
  JOIN products p ON vs.id = p.id  
ORDER BY  
  vs.distance  
LIMIT  
  24
```

## Plan

Uses embedding_scann index.

```text
Limit (cost=2651.99..2905.07 rows=24 width=664) (actual time=8.756..9.155 rows=24 loops=1)  
-> Nested Loop (cost=2651.99..3179.25 rows=50 width=664) (actual time=8.755..9.152 rows=24 loops=1)  
-> Limit (cost=2651.70..2807.37 rows=50 width=16) (actual time=8.718..9.053 rows=24 loops=1)  
-> Index Scan using embedding_scann on products p_1 (cost=2651.70..32874.37 rows=9707 width=16) (actual time=8.716..9.050 rows=24 loops=1)  
Order By: (product_embedding <=> '[0.0075428765,-0.015070019,...,-0.018507553]'::vector)  
Filter: ((product_embedding <=> '[0.0075428765,-0.015070019,…,-0.018507553]'::vector) < '0.5'::double precision)  
-> Index Scan using products_pkey on products p (cost=0.29..7.42 rows=1 width=632) (actual time=0.002..0.002 rows=1 loops=24)  
Index Cond: (id = p_1.id)  
Planning Time: 250.290 ms  
Execution Time: 9.283 ms
```

# Upgrade Extensions

## Versions Before

SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'alloydb_scann');

```json
[  
  {  
    "extname": "vector",  
    "extversion": "0.8.0.google-4"  
  },  
  {  
    "extname": "alloydb_scann",  
    "extversion": "0.1.2"  
  }  
]
```

## Upgrade Statement

```sql
ALTER EXTENSION vector UPDATE TO '0.8.1.google-1';  
ALTER EXTENSION alloydb_scann UPDATE TO '0.1.3';
```

## Versions After

```sql
SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'alloydb_scann');

[  
  {  
    "extname": "vector",  
    "extversion": "0.8.1.google-1"  
  },  
  {  
    "extname": "alloydb_scann",  
    "extversion": "0.1.3"  
  }  
]
```

# Test Query Without Index Rebuild

## Plan

Still uses embedding_scann index.

```text
Limit (cost=2651.99..2905.07 rows=24 width=664) (actual time=43.539..44.615 rows=24 loops=1)  
-> Nested Loop (cost=2651.99..3179.25 rows=50 width=664) (actual time=43.538..44.611 rows=24 loops=1)  
-> Limit (cost=2651.70..2807.37 rows=50 width=16) (actual time=43.414..44.315 rows=24 loops=1)  
-> Index Scan using embedding_scann on products p_1 (cost=2651.70..32874.37 rows=9707 width=16) (actual time=43.411..44.310 rows=24 loops=1)  
Order By: (product_embedding <=> '[0.0075428765,-0.015070019,...-0.018507553]'::vector)  
Filter: ((product_embedding <=> '[0.0075428765,-0.015070019,...,-0.018507553]'::vector) < '0.5'::double precision)  
-> Index Scan using products_pkey on products p (cost=0.29..7.42 rows=1 width=632) (actual time=0.003..0.003 rows=1 loops=24)  
Index Cond: (id = p_1.id)  
Planning Time: 275.382 ms  
Execution Time: 44.848 ms
```

# Optional: Rebuild Index

## Create Index

Create index embedding_scann_2 concurrently so that the other index remains in use during this long-running operation.

```sql
CREATE INDEX embedding_scann ON products  
  USING scann (product_embedding cosine)  
  WITH (num_leaves=2);
```

## Run Query While Index Builds

### Plan

Uses old embedding_scann index:

```text
Limit (cost=2651.99..2905.07 rows=24 width=664) (actual time=20.043..20.870 rows=24 loops=1)  
-> Nested Loop (cost=2651.99..3179.25 rows=50 width=664) (actual time=20.041..20.866 rows=24 loops=1)  
-> Limit (cost=2651.70..2807.37 rows=50 width=16) (actual time=19.862..20.239 rows=24 loops=1)  
-> Index Scan using embedding_scann on products p_1 (cost=2651.70..32874.37 rows=9707 width=16) (actual time=19.860..20.234 rows=24 loops=1)  
Order By: (product_embedding <=> '[0.0075428765,-0.015070019,...,-0.018507553]'::vector)  
Filter: ((product_embedding <=> '[0.0075428765,-0.015070019,...,-0.018507553]'::vector) < '0.5'::double precision)  
-> Index Scan using products_pkey on products p (cost=0.29..7.42 rows=1 width=632) (actual time=0.018..0.018 rows=1 loops=24)  
Index Cond: (id = p_1.id)  
Planning Time: 280.127 ms  
Execution Time: 21.397 ms
```

## Run Query After Index Build

### Plan

Uses new embedding_scann_2 index,

```text
Limit (cost=2356.99..2610.07 rows=24 width=664) (actual time=8.298..8.664 rows=24 loops=1)  
-> Nested Loop (cost=2356.99..2884.25 rows=50 width=664) (actual time=8.298..8.661 rows=24 loops=1)  
-> Limit (cost=2356.70..2512.37 rows=50 width=16) (actual time=8.259..8.565 rows=24 loops=1)  
-> Index Scan using embedding_scann_2 on products p_1 (cost=2356.70..32579.37 rows=9707 width=16) (actual time=8.257..8.561 rows=24 loops=1)  
Order By: (product_embedding <=> '[0.0075428765,-0.015070019,...,-0.018507553]'::vector)  
Filter: ((product_embedding <=> '[0.0075428765,-0.015070019,...,-0.018507553]'::vector) < '0.5'::double precision)  
-> Index Scan using products_pkey on products p (cost=0.29..7.42 rows=1 width=632) (actual time=0.002..0.002 rows=1 loops=24)  
Index Cond: (id = p_1.id)  
Planning Time: 245.242 ms  
Execution Time: 8.790 ms  
```

## Optional: Rename Index

This is only necessary if you have code that uses index hints or otherwise relies on index naming conventions.

### Rename Script

This operation took only 317.0 ms in my lab environment (versus index build time of several minutes). 

```sql
BEGIN;  
DROP INDEX embedding_scann;  
ALTER INDEX embedding_scann_2 RENAME TO embedding_scann;  
COMMIT;
```

### Run Query

Uses the new index, newly named embedding_scann.

```text
Limit (cost=2356.99..2610.07 rows=24 width=664) (actual time=7.708..8.043 rows=24 loops=1)  
-> Nested Loop (cost=2356.99..2884.25 rows=50 width=664) (actual time=7.708..8.040 rows=24 loops=1)  
-> Limit (cost=2356.70..2512.37 rows=50 width=16) (actual time=7.680..7.955 rows=24 loops=1)  
-> Index Scan using embedding_scann on products p_1 (cost=2356.70..32579.37 rows=9707 width=16) (actual time=7.679..7.952 rows=24 loops=1)  
Order By: (product_embedding <=> '[0.0075428765,-0.015070019,-...,-0.018507553]'::vector)  
Filter: ((product_embedding <=> '[0.0075428765,-0.015070019,...,-0.018507553]'::vector) < '0.5'::double precision)  
-> Index Scan using products_pkey on products p (cost=0.29..7.42 rows=1 width=632) (actual time=0.002..0.002 rows=1 loops=24)  
Index Cond: (id = p_1.id)  
Planning Time: 286.245 ms  
Execution Time: 8.151 ms
```

# Summary

This guide walked through the process of upgrading the `vector` (pgvector) and `alloydb_scann` extensions on an AlloyDB instance. It demonstrated how to verify the upgrade using a semantic search query plan and provided an optional procedure for online index rebuilding to ensure the new extension version is fully utilized.

# Next Steps

1. **Validate in Staging**: Always perform extension upgrades in a non-production environment first to verify compatibility with your specific dataset and workload.
2. **Monitor Performance**: After upgrading in production, keep an eye on query latency and index usage (via `EXPLAIN ANALYZE`) to confirm that the planner is selecting the optimal index.
3. **Schedule Index Rebuilds**: If you decide to rebuild indexes, plan for the necessary resources (CPU/Memory) or maintenance window, although `CONCURRENTLY` allows this to happen online.

# Disclaimer

This is not an officially supported Google product.

This software is provided "as is", without warranty of any kind, expressed or implied, including but not limited to, the warranties of merchantability, fitness for a particular purpose, and/or infringement.

See license file for additional details.