#!/usr/bin/env bash

# Load env variables
source ./env.sh

#
# Create the Artifact Registry repository:
#
echo "Creating the Artifact Registry repository"
gcloud artifacts repositories create cymbalshops \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT_ID"
