#!/usr/bin/env bash

###
### Deploys the Cymbal Shops StyleSearch app
###
### NOTE: you need the latest version of gcloud to deploy this
###

# Deploy the registry
echo "Deploying front end dependencies."
source ./deployment/deploy-registry.sh

# Deploy the front end.
echo "Deploying the front end."
source ./deployment/deploy-frontend.sh

echo "Install complete."
