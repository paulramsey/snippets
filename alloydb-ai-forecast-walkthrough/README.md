# TimesFM 2.5 + AlloyDB AI (`ai.forecast`): Programmatic Deployment & Scale-to-Zero

This guide walks through deploying Google's **TimesFM 2.5** time-series foundation model on **Vertex AI** using its Model Garden serving container, configuring **scale-to-zero (`min_replica_count=0`)** so you don't pay for idle GPUs, registering the endpoint in **AlloyDB for PostgreSQL**, and running **`ai.forecast()`** for forecasting and anomaly detection.

The official AlloyDB documentation points to a Console UI "One-click deployment" or an interactive Colab Enterprise notebook that leaves a GPU node running 24/7. Automating this end-to-end via CLI/SDK surfaces several subtle container, IAM, and endpoint constraints—each step below incorporates the exact fixes so deployment succeeds on the first run.

---

## Table of Contents

1. [Lessons Learned & Common Pitfalls](#lessons-learned--common-pitfalls)
2. [Prerequisites & Configuration](#prerequisites--configuration)
3. [Authenticate](#authenticate)
4. [Step 1: Stage Model Weights & Configure IAM](#step-1-stage-model-weights--configure-iam)
5. [Step 2: Deploy TimesFM to Vertex AI (with Scale-to-Zero)](#step-2-deploy-timesfm-to-vertex-ai-with-scale-to-zero)
   - [Option A: Idempotent Python Script (Recommended)](#option-a-idempotent-python-script-recommended)
   - [Option B: `gcloud ai` CLI](#option-b-gcloud-ai-cli)
6. [Step 3: Configure AlloyDB & Register the Model](#step-3-configure-alloydb--register-the-model)
7. [Step 4: Run `ai.forecast()` Queries](#step-4-run-aiforecast-queries)
   - [4a. Quick Smoke Test](#4a-quick-smoke-test)
   - [4b. Daily Aggregated Anomaly Detection](#4b-daily-aggregated-anomaly-detection)
   - [4c. Irregular Event / Transaction-Level Sequences](#4c-irregular-event--transaction-level-sequences)
8. [Updating an Existing Always-On Endpoint to Scale-to-Zero](#updating-an-existing-always-on-endpoint-to-scale-to-zero)
9. [Cleanup](#cleanup)
10. [Disclaimer](#disclaimer)

---

## Lessons Learned & Common Pitfalls

| Challenge | Symptom / Error | Root Cause & Fix |
|---|---|---|
| **Container crashes on startup** | `Model server exited unexpectedly` during deployment | Both `MODEL_ID` and `AIP_STORAGE_URI` must point to the **exact variant folder** in GCS (`gs://<BUCKET>/timesfm/timesfm-2.5-200m-flax`), and `TIMESFM_CONTEXT=0` + `TIMESFM_HORIZON=0` must be set to allow dynamic context/horizon lengths per query. |
| **Recurring `403 Forbidden` reading GCS weights** | Container fails to pull weights even after granting IAM to the Vertex AI Service Agent | Vertex AI spins up dynamic tenant service accounts (`custom-online-prediction@...-tp.iam.gserviceaccount.com`) that lack bucket permissions. **Fix:** Grant GCS read access to a stable service account in your project and **explicitly pass `service_account` (`--service-account`)** when deploying the model. |
| **AlloyDB cannot reach Dedicated Endpoints** | Registration or prediction fails against `*.prediction.vertexai.goog` | AlloyDB `google_ml` `:predict` integration requires a **Public Shared Endpoint** (`dedicated_endpoint_enabled=False`) using the standard `https://<REGION>-aiplatform.googleapis.com/v1/...:predict` URL. |
| **24/7 GPU cost on idle endpoints** | Continuous billing for `g2-standard-8` + `NVIDIA_L4` | Set `min_replica_count=0` and `max_replica_count=1`. Vertex AI scales the GPU replicas down to `0` when inactive and spins one up automatically on demand. |
| **Cold-start timeouts after scale-down** | First `ai.forecast()` query after idle period hangs or times out | Spinning up a fresh `NVIDIA_L4` replica and loading weights takes **3–5 minutes**. Increase `statement_timeout` (e.g., `SET statement_timeout = '10min';`) on cold-start queries or send a lightweight warm-up forecast. |
| **In-place scale-to-zero updates fail** | Cannot mutate `min_replica_count` from `1` to `0` on a live deployment | Vertex AI requires **undeploying** the model from the endpoint first and **redeploying** with `min_replica_count=0` (~15–20 minutes). |
| **Irregular timestamps don't join cleanly** | `LEFT JOIN` on `forecast_timestamp = actual_timestamp` returns `NULL`s | `ai.forecast()` emits synthetic regular intervals. For irregular event sequences (e.g., individual card swipes), join forecasted rows to actuals on `ROW_NUMBER() OVER (ORDER BY ...)`. |

---

## Prerequisites & Configuration

- An **AlloyDB for PostgreSQL** cluster and primary instance in the target project/region.
- Set your environment variables before running the commands below:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"
export BUCKET_NAME="${PROJECT_ID}-timesfm-models"
export MODEL_VARIANT="timesfm-2.5-200m-flax"

# AlloyDB identifiers (used if updating instance flags via gcloud)
export ALLOYDB_CLUSTER="YOUR_ALLOYDB_CLUSTER"
export ALLOYDB_INSTANCE="YOUR_ALLOYDB_PRIMARY_INSTANCE"

# Derive Project Number and Service Accounts
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

# Dedicated custom SA recommended in production; Compute Engine default SA shown for simplicity
export SERVING_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
export ALLOYDB_SA="service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com"
```

---

## Authenticate

```bash
# Authenticate with gcloud
gcloud auth login
gcloud auth application-default login
gcloud auth application-default set-quota-project "$PROJECT_ID"
gcloud config set project "$PROJECT_ID"
```

---

## Step 1: Stage Model Weights & Configure IAM

1. **Enable required APIs:**

   ```bash
   gcloud services enable \
     aiplatform.googleapis.com \
     storage.googleapis.com \
     alloydb.googleapis.com \
     --project="$PROJECT_ID"
   ```

2. **Create a regional GCS bucket and copy the TimesFM 2.5 weights from Model Garden's public bucket:**

   ```bash
   gcloud storage buckets create "gs://${BUCKET_NAME}" \
     --project="$PROJECT_ID" \
     --location="$REGION" \
     --uniform-bucket-level-access

   gcloud storage cp -R \
     "gs://vertex-model-garden-public-us/timesfm/${MODEL_VARIANT}" \
     "gs://${BUCKET_NAME}/timesfm/"
   ```

   Verify that the weights landed at `gs://${BUCKET_NAME}/timesfm/${MODEL_VARIANT}`:

   ```bash
   gcloud storage ls "gs://${BUCKET_NAME}/timesfm/${MODEL_VARIANT}/"
   ```

3. **Grant GCS permissions to the serving service account:**

   > **Why:** Without pinning a service account that has access to `gs://${BUCKET_NAME}`, Vertex AI uses an ephemeral tenant service account (`custom-online-prediction@...-tp.iam.gserviceaccount.com`) and fails with `403 Forbidden` while pulling weights.

   ```bash
   # Least-privilege bucket read/write access on the model bucket
   gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
     --member="serviceAccount:${SERVING_SA}" \
     --role="roles/storage.objectAdmin"
   ```

   *(Note: If you hit cross-bucket staging errors in restricted orgs, granting project-level `roles/storage.objectViewer` or `roles/storage.admin` to `${SERVING_SA}` resolves it.)*

4. **Grant the AlloyDB Service Agent permission to invoke Vertex AI endpoints:**

   ```bash
   gcloud projects add-iam-policy-binding "$PROJECT_ID" \
     --member="serviceAccount:${ALLOYDB_SA}" \
     --role="roles/aiplatform.user"
   ```

---

## Step 2: Deploy TimesFM to Vertex AI (with Scale-to-Zero)

Deployment provisions a `g2-standard-8` VM with 1x `NVIDIA_L4` GPU using the Model Garden TimesFM 2.5 container (`timesfm-serve-v2p5:latest`) and takes **15–20 minutes**.

### Option A: Idempotent Python Script (Recommended)

Failed or interrupted runs can leave duplicate models and endpoints behind. The script below checks for existing resources by `display_name` before creating them, configures a **Shared Endpoint** (`dedicated_endpoint_enabled=False`), pins `service_account`, and enables **scale-to-zero** (`min_replica_count=0`, `max_replica_count=1`).

> *Note on SDK choice:* While generative model calls should use `google-genai`, `google-cloud-aiplatform` remains the control-plane SDK for Vertex AI Model Registry and Online Prediction Endpoints. If you prefer zero Python dependencies, skip to [Option B](#option-b-gcloud-ai-cli).

1. **Set up a Python virtual environment:**

   ```bash
   # Option 1: uv (preferred)
   uv venv .venv
   source .venv/bin/activate
   uv pip install google-cloud-aiplatform

   # Option 2: standard venv + pip3
   python3 -m venv .venv
   source .venv/bin/activate
   pip3 install google-cloud-aiplatform
   ```

2. **Save the following script as `deploy_timesfm.py` and run it:**

   ```python
   import os
   from google.cloud import aiplatform

   PROJECT_ID = os.environ["PROJECT_ID"]
   REGION = os.environ.get("REGION", "us-central1")
   BUCKET_NAME = os.environ["BUCKET_NAME"]
   MODEL_VARIANT = os.environ.get("MODEL_VARIANT", "timesfm-2.5-200m-flax")
   SERVING_SA = os.environ["SERVING_SA"]

   MODEL_URI = f"gs://{BUCKET_NAME}/timesfm/{MODEL_VARIANT}"
   STAGING_BUCKET = f"gs://{BUCKET_NAME}/timesfm/staging"
   SERVE_DOCKER_URI = (
       "us-docker.pkg.dev/vertex-ai-restricted/"
       "vertex-vision-model-garden-dockers/timesfm-serve-v2p5:latest"
   )

   ENDPOINT_DISPLAY_NAME = "timesfm-2.5-gpu-endpoint"
   MODEL_DISPLAY_NAME = "timesfm-2.5-gpu"

   print(f"Initializing Vertex AI control plane in {PROJECT_ID} ({REGION})...")
   aiplatform.init(project=PROJECT_ID, location=REGION, staging_bucket=STAGING_BUCKET)

   # 1. Reuse or create a Shared (non-dedicated) Endpoint
   endpoints = aiplatform.Endpoint.list(filter=f'display_name="{ENDPOINT_DISPLAY_NAME}"')
   if endpoints:
       endpoint = endpoints[0]
       print(f"Reusing existing endpoint: {endpoint.resource_name}")
   else:
       print("Creating Shared Endpoint (dedicated_endpoint_enabled=False)...")
       endpoint = aiplatform.Endpoint.create(
           display_name=ENDPOINT_DISPLAY_NAME,
           dedicated_endpoint_enabled=False,  # Required for AlloyDB google_ml integration
       )

   # 2. Reuse or upload the Model to Vertex AI Model Registry
   models = aiplatform.Model.list(filter=f'display_name="{MODEL_DISPLAY_NAME}"')
   if models:
       model = models[0]
       print(f"Reusing existing model: {model.resource_name}")
   else:
       print("Uploading TimesFM 2.5 model to Model Registry...")
       model = aiplatform.Model.upload(
           display_name=MODEL_DISPLAY_NAME,
           serving_container_image_uri=SERVE_DOCKER_URI,
           serving_container_ports=[8080],
           serving_container_predict_route="/predict",
           serving_container_health_route="/health",
           serving_container_environment_variables={
               "MODEL_ID": MODEL_URI,
               "AIP_STORAGE_URI": MODEL_URI,
               "TIMESFM_CONTEXT": "0",  # Dynamic context window
               "TIMESFM_HORIZON": "0",  # Dynamic forecast horizon
           },
           model_garden_source_model_name="publishers/google/models/timesfm2p5",
       )

   # 3. Deploy to Endpoint with Scale-to-Zero (if not already deployed)
   already_deployed = any(
       dm.model == model.resource_name for dm in endpoint.list_models()
   )
   if already_deployed:
       print("Model is already deployed to this endpoint.")
   else:
       print("Deploying model with scale-to-zero (takes ~15-20 minutes)...")
       model.deploy(
           endpoint=endpoint,
           machine_type="g2-standard-8",
           accelerator_type="NVIDIA_L4",
           accelerator_count=1,
           min_replica_count=0,  # Scale to zero when idle
           max_replica_count=1,
           deploy_request_timeout=1800,
           enable_access_logging=True,
           service_account=SERVING_SA,  # Prevents dynamic tenant SA 403 errors
           sync=True,
       )

   predict_url = (
       f"https://{REGION}-aiplatform.googleapis.com/v1/"
       f"projects/{PROJECT_ID}/locations/{REGION}/endpoints/{endpoint.name}:predict"
   )
   print("\nDeployment complete!")
   print(f"Endpoint ID:  {endpoint.name}")
   print(f"Predict URL:  {predict_url}")
   ```

   ```bash
   python3 deploy_timesfm.py
   ```

---

### Option B: `gcloud ai` CLI

If you prefer pure `gcloud` commands without Python:

```bash
SERVE_DOCKER_URI="us-docker.pkg.dev/vertex-ai-restricted/vertex-vision-model-garden-dockers/timesfm-serve-v2p5:latest"
MODEL_URI="gs://${BUCKET_NAME}/timesfm/${MODEL_VARIANT}"

# 1. Create a Shared Endpoint (do NOT pass --dedicated-endpoint)
gcloud ai endpoints create \
  --display-name="timesfm-2.5-gpu-endpoint" \
  --region="$REGION" \
  --project="$PROJECT_ID"

export ENDPOINT_ID=$(gcloud ai endpoints list \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --filter="display_name=timesfm-2.5-gpu-endpoint" \
  --format="value(ENDPOINT_ID)" | head -n 1)

# 2. Upload Model to Vertex AI Model Registry
gcloud ai models upload \
  --display-name="timesfm-2.5-gpu" \
  --container-image-uri="$SERVE_DOCKER_URI" \
  --container-env-vars="MODEL_ID=${MODEL_URI},AIP_STORAGE_URI=${MODEL_URI},TIMESFM_CONTEXT=0,TIMESFM_HORIZON=0" \
  --container-ports=8080 \
  --container-health-route="/health" \
  --container-predict-route="/predict" \
  --region="$REGION" \
  --project="$PROJECT_ID"

export VERTEX_MODEL_ID=$(gcloud ai models list \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --filter="display_name=timesfm-2.5-gpu" \
  --format="value(MODEL_ID)" | head -n 1)

# 3. Deploy with min-replica-count=0 and explicit service account
gcloud ai endpoints deploy-model "$ENDPOINT_ID" \
  --model="$VERTEX_MODEL_ID" \
  --display-name="timesfm-2.5-deployment" \
  --machine-type="g2-standard-8" \
  --accelerator="type=nvidia-l4,count=1" \
  --min-replica-count=0 \
  --max-replica-count=1 \
  --service-account="$SERVING_SA" \
  --region="$REGION" \
  --project="$PROJECT_ID"

echo "Predict URL: https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/endpoints/${ENDPOINT_ID}:predict"
```

### Verify Scale-to-Zero Configuration

```bash
gcloud ai endpoints describe "$ENDPOINT_ID" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="yaml(deployedModels[].id,deployedModels[].dedicatedResources)"
```

> **Note:** In `gcloud` YAML/JSON output, protobuf omits zero-valued fields—so when `minReplicaCount` is `0`, you will see `maxReplicaCount: 1` under `dedicatedResources` with `minReplicaCount` omitted (whereas always-on endpoints explicitly show `minReplicaCount: 1`).

---

## Step 3: Configure AlloyDB & Register the Model

1. **Enable AlloyDB AI model support and AI Query Engine flags on your instance** (if not already set in Terraform or Console):

   ```bash
   # Inspect existing flags first so you don't overwrite other flags on the instance!
   gcloud alloydb instances describe "$ALLOYDB_INSTANCE" \
     --cluster="$ALLOYDB_CLUSTER" \
     --region="$REGION" \
     --project="$PROJECT_ID" \
     --format="yaml(databaseFlags)"
   ```

   Ensure both flags below are set to `on` on your AlloyDB instance:
   - `google_ml_integration.enable_model_support = on`
   - `google_ml_integration.enable_ai_query_engine = on`

2. **Install/upgrade `google_ml_integration` (`>= 1.4.5` required for `ai.forecast`)** in your target database via `psql` or AlloyDB Studio:

   ```sql
   CREATE EXTENSION IF NOT EXISTS google_ml_integration CASCADE;
   ALTER EXTENSION google_ml_integration UPDATE;

   -- Must be 1.4.5 or higher
   SELECT extversion FROM pg_extension WHERE extname = 'google_ml_integration';
   ```

3. **Register the Vertex AI TimesFM endpoint in AlloyDB:**

   Replace `<PROJECT_ID>`, `<REGION>`, and `<ENDPOINT_ID>` with the values output in Step 2:

   ```sql
   CALL google_ml.create_model(
     model_id             => 'timesfm_v2',
     model_qualified_name => 'timesfm_v2',
     model_type           => 'ts_forecasting',
     model_provider       => 'google',
     model_request_url    => 'https://<REGION>-aiplatform.googleapis.com/v1/projects/<PROJECT_ID>/locations/<REGION>/endpoints/<ENDPOINT_ID>:predict'
   );
   ```

---

## Step 4: Run `ai.forecast()` Queries

> **Cold-Start Reminder:** If your Vertex AI endpoint has scaled down to `0` replicas, the first query will wait **3–5 minutes** while Vertex AI provisions the L4 GPU node. Raise `statement_timeout` for that session before running the first forecast:
> ```sql
> SET statement_timeout = '10min';
> ```

### 4a. Quick Smoke Test

Validate the end-to-end AlloyDB -> Vertex AI connection without needing any existing tables:

```sql
SET statement_timeout = '10min';

SELECT *
FROM ai.forecast(
  source_query => '
    SELECT my_timestamp, my_data_value
    FROM (
      VALUES
        (TIMESTAMP ''2025-01-01'', 10.0),
        (TIMESTAMP ''2025-01-02'', 12.0),
        (TIMESTAMP ''2025-01-03'', 11.0),
        (TIMESTAMP ''2025-01-04'', 13.0),
        (TIMESTAMP ''2025-01-05'', 15.0),
        (TIMESTAMP ''2025-01-06'', 14.0),
        (TIMESTAMP ''2025-01-07'', 16.0),
        (TIMESTAMP ''2025-01-08'', 18.0),
        (TIMESTAMP ''2025-01-09'', 17.0),
        (TIMESTAMP ''2025-01-10'', 20.0)
    ) AS t(my_timestamp, my_data_value)
  ',
  model_id      => 'timesfm_v2',
  data_col      => 'my_data_value',
  timestamp_col => 'my_timestamp',
  horizon       => 7,
  conf_level    => 0.90
);
```

### 4b. Daily Aggregated Anomaly Detection

For large operational tables (e.g., millions of `transactions`), aggregate into regular buckets (`DATE_TRUNC('day', ...)`) inside `source_query` and compare actuals against the prediction interval bounds:

```sql
WITH forecast_data AS (
  SELECT *
  FROM ai.forecast(
    source_query  => '
      SELECT DATE_TRUNC(''day'', date) AS my_timestamp,
             SUM(amount) AS my_data_value
      FROM transactions
      WHERE date >= ''2025-01-01'' AND date < ''2025-02-01''
      GROUP BY 1
      ORDER BY 1
    ',
    model_id      => 'timesfm_v2',
    data_col      => 'my_data_value',
    timestamp_col => 'my_timestamp',
    horizon       => 7,
    conf_level    => 0.90
  )
),
actual_data AS (
  SELECT DATE_TRUNC('day', date) AS my_timestamp,
         SUM(amount) AS actual_value
  FROM transactions
  WHERE date >= '2025-02-01' AND date < '2025-02-08'
  GROUP BY 1
)
SELECT
  f.forecast_timestamp,
  f.forecast_value,
  a.actual_value,
  f.prediction_interval_lower_bound,
  f.prediction_interval_upper_bound,
  CASE
    WHEN a.actual_value IS NULL THEN 'No Data'
    WHEN a.actual_value < f.prediction_interval_lower_bound THEN 'LOW ANOMALY'
    WHEN a.actual_value > f.prediction_interval_upper_bound THEN 'HIGH ANOMALY'
    ELSE 'Normal'
  END AS status
FROM forecast_data f
LEFT JOIN actual_data a
  ON f.forecast_timestamp = a.my_timestamp
ORDER BY f.forecast_timestamp;
```

### 4c. Irregular Event / Transaction-Level Sequences

TimesFM assumes evenly spaced steps and generates synthetic `forecast_timestamp` intervals. When forecasting raw event sequences (such as the next `N` swipes on a credit card), join forecasted steps to actual events using **`ROW_NUMBER()`** rather than timestamp equality:

```sql
WITH forecast_data AS (
  SELECT *,
         ROW_NUMBER() OVER (ORDER BY forecast_timestamp) AS seq_num
  FROM ai.forecast(
    source_query  => '
      SELECT date AS my_timestamp,
             amount AS my_data_value
      FROM transactions
      WHERE card_id = 3952
        AND date >= ''2025-01-01'' AND date < ''2025-06-01''
      ORDER BY date
    ',
    model_id      => 'timesfm_v2',
    data_col      => 'my_data_value',
    timestamp_col => 'my_timestamp',
    horizon       => 5,
    conf_level    => 0.90
  )
),
actual_data AS (
  SELECT date AS actual_timestamp,
         amount AS actual_value,
         id AS transaction_id,
         ROW_NUMBER() OVER (ORDER BY date) AS seq_num
  FROM transactions
  WHERE card_id = 3952
    AND date >= '2025-06-01'
  ORDER BY date
  LIMIT 5
)
SELECT
  f.seq_num,
  f.forecast_value,
  a.actual_timestamp,
  a.actual_value,
  a.transaction_id,
  f.prediction_interval_lower_bound,
  f.prediction_interval_upper_bound,
  CASE
    WHEN a.actual_value IS NULL THEN 'No Data'
    WHEN a.actual_value < f.prediction_interval_lower_bound THEN 'LOW ANOMALY'
    WHEN a.actual_value > f.prediction_interval_upper_bound THEN 'HIGH ANOMALY'
    ELSE 'Normal'
  END AS status
FROM forecast_data f
LEFT JOIN actual_data a
  ON f.seq_num = a.seq_num
ORDER BY f.seq_num;
```

---

## Updating an Existing Always-On Endpoint to Scale-to-Zero

If you previously deployed TimesFM via the Console or Colab notebook with `min_replica_count=1`, Vertex AI will not let you change `min_replica_count` to `0` in place. Undeploy the active model from the endpoint (preserving the Endpoint ID so your AlloyDB `model_request_url` stays unchanged!) and redeploy with `--min-replica-count=0`:

```bash
# 1. Look up the DeployedModel ID (distinct from the Model Registry ID)
DEPLOYED_MODEL_ID=$(gcloud ai endpoints describe "$ENDPOINT_ID" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="value(deployedModels[0].id)")

# 2. Undeploy from the endpoint
gcloud ai endpoints undeploy-model "$ENDPOINT_ID" \
  --deployed-model-id="$DEPLOYED_MODEL_ID" \
  --region="$REGION" \
  --project="$PROJECT_ID"

# 3. Redeploy to the SAME endpoint with min-replica-count=0
gcloud ai endpoints deploy-model "$ENDPOINT_ID" \
  --model="$VERTEX_MODEL_ID" \
  --display-name="timesfm-2.5-deployment" \
  --machine-type="g2-standard-8" \
  --accelerator="type=nvidia-l4,count=1" \
  --min-replica-count=0 \
  --max-replica-count=1 \
  --service-account="$SERVING_SA" \
  --region="$REGION" \
  --project="$PROJECT_ID"
```

---

## Cleanup

To avoid incurring storage or compute charges when finished, remove the AlloyDB model registration, Vertex AI endpoint/model, and staged GCS weights:

1. **Drop the model registration in AlloyDB:**

   ```sql
   CALL google_ml.drop_model('timesfm_v2');
   ```

2. **Undeploy and delete the Vertex AI Endpoint, Model, and GCS bucket:**

   ```bash
   # Undeploy any deployed models on the endpoint
   DEPLOYED_MODEL_ID=$(gcloud ai endpoints describe "$ENDPOINT_ID" \
     --region="$REGION" \
     --project="$PROJECT_ID" \
     --format="value(deployedModels[0].id)")

   if [ -n "$DEPLOYED_MODEL_ID" ]; then
     gcloud ai endpoints undeploy-model "$ENDPOINT_ID" \
       --deployed-model-id="$DEPLOYED_MODEL_ID" \
       --region="$REGION" \
       --project="$PROJECT_ID"
   fi

   # Delete Vertex AI Endpoint
   gcloud ai endpoints delete "$ENDPOINT_ID" \
     --region="$REGION" \
     --project="$PROJECT_ID" \
     --quiet

   # Delete Model from Vertex AI Model Registry
   gcloud ai models delete "$VERTEX_MODEL_ID" \
     --region="$REGION" \
     --project="$PROJECT_ID" \
     --quiet

   # Delete staged model weights bucket (only if created exclusively for this guide)
   gcloud storage rm -r "gs://${BUCKET_NAME}"
   ```

---

## Disclaimer

This code is intended for illustrative purposes and is not an officially supported Google product. It is provided "as is", without warranty of any kind. You should review, test, and adapt these patterns to your specific security and performance requirements before deploying in a production environment.
