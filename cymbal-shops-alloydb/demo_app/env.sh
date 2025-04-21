#!/usr/bin/env bash

# Update env variables here
export REGION="us-central1"
export ZONE="us-central1-a"
export IMAGE_BUCKET="genwealth-gen-vid"
export ALLOYDB_CLUSTER="alloydb-cluster-magic"
export ALLOYDB_INSTANCE="alloydb-instance-magic"
export VPC_NETWORK=demo-vpc

# Prompt for AlloyDB password
if [[ -z "$ALLOYDB_PASSWORD" ]]; then
  # If it's empty/unset, prompt the user
  read -r -s -p "Enter password for the postgres database user: " ALLOYDB_PASSWORD
  # Add a newline after the prompt for cleaner output, only if we prompted
  echo ""
fi

# Keep all defaults below
export PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
export ALLOYDB_IP=$(gcloud alloydb instances describe $ALLOYDB_INSTANCE --cluster=$ALLOYDB_CLUSTER --region=$REGION --view=BASIC --format=json 2>/dev/null | jq -r .ipAddress)
export PGPORT=5432
export PGDATABASE=ecom
export PGUSER=postgres
export PGHOST=${ALLOYDB_IP}
export PGPASSWORD=${ALLOYDB_PASSWORD}
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
export ORGANIZATION=$(gcloud projects get-ancestors ${PROJECT_ID} --format=json | jq -r '.[] | select(.type == "organization").id')
export VPC_SUBNET=$VPC_NETWORK
export VPC_NAME=$VPC_NETWORK

