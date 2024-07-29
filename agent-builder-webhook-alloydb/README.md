# Dialogflow CX (Agent Builder) Chat App Webhook for AlloyDB

This snippet provides a simple webhook for integrating real-time [AlloyDB](https://cloud.google.com/alloydb) data with [Dialogflow CX](https://cloud.google.com/dialogflow/cx/docs/basics) (Vertex AI Chat Apps). It empowers you to execute SQL queries directly from your Dialogflow CX agent, seamlessly presenting the results or any potential errors within the chat interface.

## Features

* Static SQL execution: Execute predefined SQL queries stored in Dialogflow CX parameters.
* Parameterized SQL execution: Execute SQL queries that incorporate dynamic parameters derived from the user's conversation context.
* Table formatting: Present successful query results in a well-structured HTML table within the chat.
* Error handling: Provides clear error messages within the chat interface if SQL queries encounter issues.
* [Dialogflow Messenger](https://cloud.google.com/dialogflow/cx/docs/concept/integration/dialogflow-messenger) formatting: Output is structured to take advantage of [`richContent`](https://cloud.google.com/dialogflow/cx/docs/concept/integration/dialogflow-messenger/fulfillment) formatting in Dialogflow Messenger

> IMPORTANT: As always, least privilege best practices apply. Use a service account with minimal grants in your database to prevent data leakage or data corruption.

## Requirements

* Python 3.11 or higher
* Google Cloud environment
* AlloyDB instance
* Dialogflow CX agent

## Deployment

1. Update the environment variables in the gcloud command below to match your environment, then run it in [Cloud Shell](https://cloud.google.com/shell) to deploy the webhook as a [Cloud Function](https://cloud.google.com/functions):


    ```bash
    # Set environment variables
    REGION=<YOUR_REGION>
    PROJECT_ID=<YOUR_PROJECT_ID>
    VPC_CONNECTOR=<YOUR_VPC_CONNECTOR>
    ALLOYDB_CLUSTER=<YOUR_ALLOYDB_CLUSTER>
    ALLOYDB_INSTANCE=<YOUR_ALLOYDB_INSTANCE>
    ALLOYDB_DATABASE=<YOUR_ALLOYDB_DATABASE>
    ALLOYDB_USER=<YOUR_ALLOYDB_USER>
    ALLOYDB_PASSWORD=<YOUR_ALLOYDB_PASSWORD>

    # Create AlloyDB password secret
    gcloud secrets create alloydb-password-"${PROJECT_ID}" \
    --replication-policy="automatic"

    echo -n "$ALLOYDB_PASSWORD" |
    gcloud secrets versions add alloydb-password-"${PROJECT_ID}" --data-file=-

    # Create Cloud Function
    gcloud functions deploy alloydb-webhook \
    --region="${REGION}" \
    --runtime=python311 \
    --source="./agent-builder-webhook-alloydb" \
    --entry-point="alloydb_webhook" \
    --set-env-vars="REGION=${REGION},PROJECT_ID=${PROJECT_ID},ALLOYDB_CLUSTER=${ALLOYDB_CLUSTER},ALLOYDB_INSTANCE=${ALLOYDB_INSTANCE},ALLOYDB_DATABASE=${ALLOYDB_DATABASE},ALLOYDB_USER=${ALLOYDB_USER}" \
    --set-secrets "ALLOYDB_PASSWORD=alloydb-password-${PROJECT_ID}:1" \
    --egress-settings=private-ranges-only \
    --vpc-connector=${VPC_CONNECTOR} \
    --timeout=60s \
    --max-instances=100 \
    --ingress-settings=all \
    --memory=1gi \
    --trigger-http
    ```

1. Configure Dialogflow CX webhook:

    - In your Dialogflow CX agent, create a webhook that points to the deployed Cloud Functions URL.
    - Set the webhook tag to either 'static' or 'parameterized' based on the nature of the query you want to execute.

## Usage

1. Static SQL:

    * Within your Dialogflow CX intent, define a parameter named 'sql' to store the SQL query you wish to execute.
    * Assign the webhook tag as 'static'.

1. Parameterized SQL:

    * Define parameters within your Dialogflow CX intent to capture dynamic values from the user's interaction.
    * In your SQL query, utilize placeholders (e.g., %s) to accommodate these dynamic parameters.
    * Set the webhook tag to 'parameterized'.

### Example

**Dialogflow CX intent:**

* Training phrases:
  * "Show me the top 10 customers"
* Parameters:
  * sql: SELECT * FROM customers LIMIT 10
* Webhook:
  * Tag: 'static'

**User input:**

* "Show me the top 10 customers"

**Webhook response:**

* If successful: An HTML table showcasing the top 10 customers retrieved from the AlloyDB database.
* If an error occurs: A clear error message detailing the issue encountered during SQL execution.

## Important Considerations

* Security: Prioritize the protection of your AlloyDB credentials and ensure restricted access to the webhook to prevent unauthorized data access.

