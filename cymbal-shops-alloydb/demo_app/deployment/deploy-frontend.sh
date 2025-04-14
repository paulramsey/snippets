#!/usr/bin/env bash

# Load env variables
source ./env.sh

if [ -z "$REGION" ]; then
  echo "REGION is not set. Please set the gcloud run/region."
  exit 1
fi

# Get the latest tags.
git fetch

#
# Build & push the container
#
echo "Building and pushing the container"
TAG_NAME=$(git describe --abbrev=0 --tags --always)
IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/cymbalshops/cymbalshops:$TAG_NAME

docker build --rm -t "$IMAGE" .
docker push "$IMAGE"

#
# Step 3: Deploy to Cloud Run
#
echo "Deploying to Cloud Run"
gcloud beta run deploy cymbalshops \
  --image="$IMAGE" \
  --execution-environment=gen2 \
  --cpu-boost \
  --network="$VPC_NETWORK" \
  --subnet="$VPC_SUBNET" \
  --vpc-egress=private-ranges-only \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --allow-unauthenticated \
  --set-env-vars=PGHOST="$PGHOST",PGPORT="$PGPORT",PGDATABASE="$PGDATABASE",PGUSER="$PGUSER",PGPASSWORD="$PGPASSWORD",PROJECT_ID="$PROJECT_ID",REGION="$REGION"
