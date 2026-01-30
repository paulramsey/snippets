#!/bin/bash
export PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project)}
export SPANNER_INSTANCE=${SPANNER_INSTANCE:-vector-db}
export SPANNER_DATABASE=${SPANNER_DATABASE:-embeddings-db}
export PORT=${PORT:-8080}

echo "Starting Spanner Search UI locally on http://localhost:$PORT..."
echo "Project: $PROJECT_ID"

# Run the app using venv python explicitly
exec ./venv/bin/python src/ui/app.py
