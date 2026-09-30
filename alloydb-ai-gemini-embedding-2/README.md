# Gemini Embedding 2 + AlloyDB AI: Custom Transforms & Auto Embeddings

This guide walks through registering Google's **`gemini-embedding-2`** model in AlloyDB, testing it with `google_ml.embedding()`, and turning on **auto embeddings** for a table.

Unlike other embedding models, `gemini-embedding-2` uses a different endpoint, location, and request/response format, so you need to write custom transform functions. Each step below explains **what** you're doing and **why**.

---

## Table of Contents

1. [Why This Model Needs Extra Setup](#why-this-model-needs-extra-setup)
2. [Prerequisites](#prerequisites)
3. [Step 1: Prepare a Table](#step-1-prepare-a-table)
4. [Step 2: Create Scalar Transforms](#step-2-create-scalar-transforms)
5. [Step 3: Create Batch Transforms](#step-3-create-batch-transforms)
6. [Step 4: Register the Model (Global Endpoint)](#step-4-register-the-model-global-endpoint)
7. [Step 5: Test with `embedding()`](#step-5-test-with-embedding)
8. [Step 6: Start Auto Embeddings (`batch_size => 1`)](#step-6-start-auto-embeddings-batch_size--1)
9. [Step 7: Drop the Embedding Config](#step-7-drop-the-embedding-config)
10. [Performance Considerations](#performance-considerations)
11. [Troubleshooting](#troubleshooting)
12. [Full Script](#full-script)

---

## Why This Model Needs Extra Setup

| | `gemini-embedding-001` | `gemini-embedding-2` |
|---|---|---|
| Model ID | `gemini-embedding-001` | `gemini-embedding-2` (**not** `gemini-embedding-002`) |
| API method | `:predict` | `:embedContent` |
| Location | Regional (e.g. `us-central1`) | `global` |
| Built-in AlloyDB transforms | ✅ Yes | ❌ No, you write your own |
| Inputs per request | Many | **One** |
| Default dimensions | 3072 | 3072 |

> ⚠️ **Common mistake:** The model is called `gemini-embedding-2`. If you register `gemini-embedding-002`, Vertex AI returns `Resource not found`.

---

## Prerequisites

- An AlloyDB for PostgreSQL cluster and instance
- The `google_ml_integration` and `vector` extensions installed:
  ```sql
  CREATE EXTENSION IF NOT EXISTS google_ml_integration CASCADE;
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
- The **Vertex AI API** (`aiplatform.googleapis.com`) enabled in your project
- The **AlloyDB service agent** granted the **Vertex AI User** role (`roles/aiplatform.user`)

**Why:** `google_ml_integration` provides model registration, `google_ml.embedding()`, and the `ai.*` auto-embedding procedures. `vector` provides the column type that stores embeddings. The service agent role is needed because the model uses `alloydb_service_agent_iam` auth, so AlloyDB calls Vertex AI as itself. Without that role, every call fails with a permission error.

---

## Step 1: Prepare a Table

This example copies an existing `products` table so you can experiment without touching production data.

```sql
DROP TABLE IF EXISTS products_test;

CREATE TABLE products_test AS SELECT * FROM products;

ALTER TABLE products_test ADD COLUMN gemini_embedding vector(3072);
```

**Why:**
- **A scratch copy** lets you re-run the walkthrough (and drop or re-create embedding configs) safely.
- **`vector(3072)`** has to match the number of dimensions `gemini-embedding-2` returns by default. If the sizes don't match, writes fail.
- **The new column starts out `NULL`.** Auto embeddings fills in rows whose embedding is `NULL`.

---

## Step 2: Create Scalar Transforms

These functions convert a **single** text value into a `gemini-embedding-2` request, and the response back into a `REAL[]`.

```sql
-- Scalar input transform: TEXT -> embedContent request body
CREATE OR REPLACE FUNCTION ge2_input_transform(model_id VARCHAR(100), input_text TEXT)
RETURNS JSON AS \$\$
  SELECT json_build_object('content',
           json_build_object('parts', json_build_array(json_build_object('text', input_text))));
\$\$ LANGUAGE sql IMMUTABLE;

-- Scalar output transform: embedContent response -> REAL[]
CREATE OR REPLACE FUNCTION ge2_output_transform(model_id VARCHAR(100), response_json JSON)
RETURNS REAL[] AS \$\$
  SELECT ARRAY(SELECT json_array_elements_text(response_json->'embedding'->'values'))::REAL[];
\$\$ LANGUAGE sql IMMUTABLE;
```

**Why:** AlloyDB's built-in transforms only understand the `gemini-embedding-001` `:predict` format (`instances[]` in, `predictions[]` out). The `:embedContent` method expects a `content.parts[]` body and returns `embedding.values`, so these functions translate between the two. `google_ml.embedding()` uses them for one-off calls.

---

## Step 3: Create Batch Transforms

Auto embeddings sends rows through the **batch** transform path, so a custom model needs batch transforms too.

```sql
-- Batch input transform: TEXT[] -> single embedContent request
CREATE OR REPLACE FUNCTION public.ge2_batch_input_transform(
    model_id TEXT,
    input TEXT[]
) RETURNS JSON
LANGUAGE plpgsql IMMUTABLE AS \$\$
BEGIN
    IF COALESCE(array_length(input, 1), 0) <> 1 THEN
        RAISE EXCEPTION 'gemini-embedding-2 :embedContent accepts exactly 1 input per request (got %). Use batch_size => 1.',
            COALESCE(array_length(input, 1), 0);
    END IF;

    RETURN json_build_object(
        'content', json_build_object(
            'parts', json_build_array(json_build_object('text', input[1]))
        )
    );
END;
\$\$;

-- Batch output transform: embedContent response -> REAL[][] (one row)
CREATE OR REPLACE FUNCTION public.ge2_batch_output_transform(
    model_id TEXT,
    model_output JSON
) RETURNS REAL[][]
LANGUAGE sql IMMUTABLE AS \$\$
    SELECT ARRAY[
        ARRAY(SELECT json_array_elements_text(model_output->'embedding'->'values'))::REAL[]
    ];
\$\$;
```

**Why each design choice matters:**

- **Why batch transforms at all?** For a custom model, auto embeddings calls `model_batch_in_transform_fn` and `model_batch_out_transform_fn`. If they're missing, auto embeddings can't talk to the model.
- **Why only one row?** The `:embedContent` endpoint takes one input per request.
- **Why raise an error instead of just using `input[1]`?** If the transform quietly embedded only the first row, the rest of the batch would be dropped. Failing loudly makes a misconfigured `batch_size` obvious right away.
- **Why return `REAL[][]` for a single row?** The batch output contract is one embedding per input row, so a batch of one is still returned as a 2-D array.

> ⚠️ **Don't pack several texts into `parts[]`.** `gemini-embedding-2` treats multiple parts in one request as **one piece of content** and returns **one combined embedding**. Nothing errors, but every row in the batch ends up with the same wrong vector.

---

## Step 4: Register the Model (Global Endpoint)

```sql
CALL google_ml.create_model(
  model_id                     => 'gemini-embedding-2',
  model_request_url            => 'https://aiplatform.googleapis.com/v1/projects/<PROJECT_ID>/locations/global/publishers/google/models/gemini-embedding-2:embedContent',
  model_provider               => 'google',
  model_type                   => 'text_embedding',
  model_auth_type              => 'alloydb_service_agent_iam',
  model_in_transform_fn        => 'ge2_input_transform',
  model_out_transform_fn       => 'ge2_output_transform',
  model_batch_in_transform_fn  => 'ge2_batch_input_transform',
  model_batch_out_transform_fn => 'ge2_batch_output_transform');
```

Replace `<PROJECT_ID>` with your Google Cloud project ID.

**Why each parameter matters:**

| Parameter | Why |
|---|---|
| `model_request_url` | Uses the **global** host (`aiplatform.googleapis.com`), **`locations/global`**, and the **`:embedContent`** method. A regional `:predict` URL fails for this model. |
| `model_type => 'text_embedding'` | Lets `google_ml.embedding()` and auto embeddings use this model. |
| `model_auth_type` | AlloyDB signs requests with its service agent, so there are no API keys to manage. |
| `model_in/out_transform_fn` | Scalar transforms from Step 2, used by `google_ml.embedding()`. |
| `model_batch_in/out_transform_fn` | Batch transforms from Step 3, used by auto embeddings. |

> 💡 To re-register (e.g. after changing the URL), run `CALL google_ml.drop_model('gemini-embedding-2');` first. You can see what's registered with `SELECT * FROM google_ml.model_info_view;`.

---

## Step 5: Test with `embedding()`

```sql
SELECT google_ml.embedding('gemini-embedding-2', 'test');

-- Optional: confirm the dimension count (expect 3072)
SELECT array_length(google_ml.embedding('gemini-embedding-2', 'test'), 1);
```

**Why:** A single call confirms that auth, the endpoint URL, and the scalar transforms all work before you point a whole table at the model. If this fails, auto embeddings will fail too, but its errors are harder to trace.

---

## Step 6: Start Auto Embeddings (`batch_size => 1`)

```sql
CALL ai.initialize_embeddings(
  model_id         => 'gemini-embedding-2',
  table_name       => 'products_test',
  content_column   => 'product_description',
  embedding_column => 'gemini_embedding',
  batch_size       => 1
);
```

**Why each argument matters:**

| Argument | Why |
|---|---|
| `model_id` | The model you registered in Step 4. |
| `table_name` | The table to embed. |
| `content_column` | The source text that gets embedded. |
| `embedding_column` | The `vector(3072)` column from Step 1. |
| `batch_size => 1` | **Required.** The batch input transform only accepts one row, because `:embedContent` only takes one input. A larger value triggers the error from Step 3. |

**Check progress:**

```sql
SELECT count(*) FILTER (WHERE gemini_embedding IS NOT NULL) AS embedded,
       count(*) FILTER (WHERE gemini_embedding IS NULL)     AS pending
FROM products_test;
```

**Try a similarity search:**

```sql
SELECT product_description
FROM products_test
ORDER BY gemini_embedding <=> google_ml.embedding('gemini-embedding-2', 'comfortable running shoes')::vector
LIMIT 5;
```

---

## Performance Considerations

> ⚠️ **`batch_size => 1` makes embedding significantly slower.**
>
> Because `gemini-embedding-2`'s `:embedContent` endpoint accepts only one input per request, auto embeddings has to make **one HTTP request per row**. Embedding models that support `batchEmbedContents` (or a similar multi-input method) can embed many rows per request, so they're much faster, especially on large tables.
>
> **AlloyDB still helps a lot here:**
> - ✅ **It parallelizes requests on the backend**, so rows aren't processed one at a time in serial.
> - ✅ **It handles retries and backoff** when you hit Vertex AI quota limits, so you don't need retry logic of your own.
>
> **What to plan for:**
> - Expect a **longer initial backfill** on large tables than you'd see with a batch-capable model.
> - **Check your Vertex AI quota** for `gemini-embedding-2`. Throughput depends on your request-per-minute quota, so raising it can speed up the backfill.
> - If throughput matters more than using this specific model, a batch-capable embedding model will backfill faster.
>
> If Vertex AI starts to support multi-input batching for `gemini-embedding-2`, you'll be able to update the model URL and batch input transform to send many rows per request, then raise `batch_size`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Resource not found` | Wrong model ID (e.g. `gemini-embedding-002`) | Use `gemini-embedding-2` |
| `400 FAILED_PRECONDITION` | Using `:predict` instead of `:embedContent` | Update `model_request_url` |
| `404` with the right model ID | Regional URL instead of `global` | Use `aiplatform.googleapis.com/.../locations/global/...` |
| `Permission denied` | Service agent is missing its Vertex AI role | Grant `roles/aiplatform.user` |
| `accepts exactly 1 input per request` | `batch_size` > 1 | Use `batch_size => 1` |
| Every row has the same vector | Several texts packed into `parts[]` | Send one input per request (Step 3) |
| Dimension mismatch on write | Column size ≠ model output size | Use `vector(3072)` (or match your configured size) |
| Model call uses a stale endpoint | An old registration with the same ID | Check `google_ml.model_info_view`, then `drop_model` and register again |

---

## Full Script

```sql
-- 0. Scratch table
DROP TABLE IF EXISTS products_test;
CREATE TABLE products_test AS SELECT * FROM products;
ALTER TABLE products_test ADD COLUMN gemini_embedding vector(3072);

-- 1. Scalar input transform
CREATE OR REPLACE FUNCTION ge2_input_transform(model_id VARCHAR(100), input_text TEXT)
RETURNS JSON AS \$\$
  SELECT json_build_object('content',
           json_build_object('parts', json_build_array(json_build_object('text', input_text))));
\$\$ LANGUAGE sql IMMUTABLE;

-- 2. Scalar output transform
CREATE OR REPLACE FUNCTION ge2_output_transform(model_id VARCHAR(100), response_json JSON)
RETURNS REAL[] AS \$\$
  SELECT ARRAY(SELECT json_array_elements_text(response_json->'embedding'->'values'))::REAL[];
\$\$ LANGUAGE sql IMMUTABLE;

-- 3. Batch input transform
CREATE OR REPLACE FUNCTION public.ge2_batch_input_transform(model_id TEXT, input TEXT[])
RETURNS JSON
LANGUAGE plpgsql IMMUTABLE AS \$\$
BEGIN
    IF COALESCE(array_length(input, 1), 0) <> 1 THEN
        RAISE EXCEPTION 'gemini-embedding-2 :embedContent accepts exactly 1 input per request (got %). Use batch_size => 1.',
            COALESCE(array_length(input, 1), 0);
    END IF;
    RETURN json_build_object(
        'content', json_build_object(
            'parts', json_build_array(json_build_object('text', input[1]))
        )
    );
END;
\$\$;

-- 4. Batch output transform
CREATE OR REPLACE FUNCTION public.ge2_batch_output_transform(model_id TEXT, model_output JSON)
RETURNS REAL[][]
LANGUAGE sql IMMUTABLE AS \$\$
    SELECT ARRAY[
        ARRAY(SELECT json_array_elements_text(model_output->'embedding'->'values'))::REAL[]
    ];
\$\$;

-- 5. Register model (replace <PROJECT_ID>)
CALL google_ml.create_model(
  model_id                     => 'gemini-embedding-2',
  model_request_url            => 'https://aiplatform.googleapis.com/v1/projects/<PROJECT_ID>/locations/global/publishers/google/models/gemini-embedding-2:embedContent',
  model_provider               => 'google',
  model_type                   => 'text_embedding',
  model_auth_type              => 'alloydb_service_agent_iam',
  model_in_transform_fn        => 'ge2_input_transform',
  model_out_transform_fn       => 'ge2_output_transform',
  model_batch_in_transform_fn  => 'ge2_batch_input_transform',
  model_batch_out_transform_fn => 'ge2_batch_output_transform');

-- 6. Test
SELECT google_ml.embedding('gemini-embedding-2', 'test');

-- 7. Auto embeddings
CALL ai.initialize_embeddings(
  model_id         => 'gemini-embedding-2',
  table_name       => 'products_test',
  content_column   => 'product_description',
  embedding_column => 'gemini_embedding',
  batch_size       => 1
);
```

