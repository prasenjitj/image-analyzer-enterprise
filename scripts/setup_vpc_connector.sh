#!/bin/bash

# Script to set up VPC connector for Cloud Functions/Cloud Run
# Usage: ./setup_vpc_connector.sh [PROJECT_ID] [REGION] [NETWORK] [CONNECTOR_NAME] [RANGE]

set -e

# Default values
PROJECT_ID="${1:-ops-excellence}"
REGION="${2:-asia-south2}"
NETWORK="${3:-image-analyzer-vpc}"
CONNECTOR_NAME="${4:-image-analyzer-connector}"
RANGE="${5:-10.8.0.0/28}"

echo "Setting up VPC connector with:"
echo "  Project ID: $PROJECT_ID"
echo "  Region: $REGION"
echo "  Network: $NETWORK"
echo "  Connector Name: $CONNECTOR_NAME"
echo "  IP Range: $RANGE"
echo ""

# Check if connector already exists
if gcloud compute networks vpc-access connectors describe "$CONNECTOR_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" &>/dev/null; then
  echo "⚠️  VPC connector '$CONNECTOR_NAME' already exists. Skipping creation."
else
  echo "Creating VPC connector..."
  gcloud compute networks vpc-access connectors create "$CONNECTOR_NAME" \
    --network="$NETWORK" \
    --region="$REGION" \
    --range="$RANGE" \
    --project="$PROJECT_ID"

  echo "✅ VPC connector created successfully!"
fi

echo ""
echo "VPC connector details:"
gcloud compute networks vpc-access connectors describe "$CONNECTOR_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="table(name,network,ipCidrRange,state)"