# Cloud SQL Maintenance Schedule & Version Tracker

This Cloud Function automates the retrieval, classification, and publication of Cloud SQL maintenance schedules.

## Configuration Variables

Set the following environment variables in your terminal before running the deployment commands.

```bash
# Core Configuration
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export SERVICE_ACCOUNT_EMAIL="your-service-account@${PROJECT_ID}.iam.gserviceaccount.com"

# Application Configuration
export TARGET_PROJECTS="project-a,project-b"  # Comma-separated list of projects to scan
export OUTPUT_BUCKET="${PROJECT_ID}-cloud-sql-report"    # Optional: GCS bucket for reports

# Scheduler Configuration
export SCHEDULER_JOB_NAME="maintenance-weekly-scan"
export SCHEDULER_SA_EMAIL="your-scheduler-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export FUNCTION_NAME="cloud-sql-maintenance-reporter"
```

## Authenticate

```bash
# Authenticate with gcloud (interactive)
gcloud auth login
```

```bash
# Configure Application Default Credentials (ADC)
gcloud auth application-default login
```

```bash
# Set the quota project for ADC
gcloud auth application-default set-quota-project $PROJECT_ID

# Set default project in gcloud config
gcloud config set project $PROJECT_ID
```

## GCS Bucket Setup (Optional)

If you plan to save the reports to GCS, create a bucket for them:

```bash

# Create the bucket
gcloud storage buckets create gs://$OUTPUT_BUCKET --project=$PROJECT_ID --location=$REGION --uniform-bucket-level-access
```

## Deployment

1.  **Deploy Command:**

    ```bash
    # Navigate to the function code directory
    cd cloud-sql-maintenance-report/function-code

    gcloud functions deploy $FUNCTION_NAME \
        --project $PROJECT_ID \
        --runtime python311 \
        --trigger-http \
        --entry-point check_maintenance_schedule \
        --source . \
        --service-account $SERVICE_ACCOUNT_EMAIL \
        --set-env-vars TARGET_PROJECTS="$TARGET_PROJECTS",OUTPUT_BUCKET="$OUTPUT_BUCKET" \
        --region $REGION
    ```

## Triggering

Create a Cloud Scheduler job to trigger this function periodically (e.g., weekly).

```bash
gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
    --project $PROJECT_ID \
    --location $REGION \
    --schedule "0 9 * * 1" \
    --uri "https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}" \
    --http-method GET \
    --oidc-service-account-email $SCHEDULER_SA_EMAIL
```

## Manual Execution

To run an ad-hoc report immediately without waiting for the scheduler:

```bash
gcloud functions call $FUNCTION_NAME \
    --project $PROJECT_ID \
    --region $REGION \
    --gen2 \
    --data '{}'
```

## Logic

The function uses a heuristic to classify updates:
1.  **Extract Base Versions:** Removes build metadata suffixes (e.g., `.R2022...`) from both the `databaseInstalledVersion` and the target version.
2.  **Compare:**
    *   **OS_PATCH**: If the base versions match (e.g., `POSTGRES_14_4` == `POSTGRES_14_4`).
    *   **MINOR_VERSION_UPGRADE**: If the base versions differ (e.g., `POSTGRES_14_4` != `POSTGRES_14_5`).

*Note: The actual availability of `availableMaintenanceVersions` depends on the specific Cloud SQL instance state and API response.*

## Cleanup

To avoid incurring charges, delete the resources created in this tutorial:

```bash
# Delete the Cloud Scheduler job
gcloud scheduler jobs delete $SCHEDULER_JOB_NAME \
    --project $PROJECT_ID \
    --location $REGION \
    --quiet

# Delete the Cloud Function
gcloud functions delete $FUNCTION_NAME \
    --project $PROJECT_ID \
    --region $REGION \
    --quiet

# (Optional) Delete the GCS bucket and all reports
gcloud storage rm -r gs://$OUTPUT_BUCKET --project=$PROJECT_ID --quiet
```

## Disclaimer

This is not an officially supported Google product.

This software is provided "as is", without warranty of any kind, expressed or implied, including but not limited to, the warranties of merchantability, fitness for a particular purpose, and/or infringement.