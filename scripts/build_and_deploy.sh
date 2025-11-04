#!/bin/bash

# Script to build and deploy the complete image analyzer system to Google Cloud
# This is a combined deployment script that calls individual server and worker scripts
# Usage: ./build_and_deploy.sh [PROJECT_ID] [REGION] [VPC_CONNECTOR]

set -e

PROJECT_ID="${1:-ops-excellence}"
REGION="${2:-asia-south2}"
VPC_CONNECTOR="${3:-image-analyzer-connector}"

echo "🚀 Starting complete system deployment..."
echo "   Project ID: $PROJECT_ID"
echo "   Region: $REGION"
echo "   VPC Connector: $VPC_CONNECTOR"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Deploy server first
echo "===== DEPLOYING SERVER ====="
echo ""
"$SCRIPT_DIR/build_and_deploy_server.sh" "$PROJECT_ID" "$REGION" "$VPC_CONNECTOR"

echo ""
echo "===== DEPLOYING WORKER ====="
echo ""
"$SCRIPT_DIR/build_and_deploy_worker.sh" "$PROJECT_ID" "$REGION" "$VPC_CONNECTOR"

echo ""
echo "🎉 Complete system deployment finished!"
echo ""

# Get the deployed URLs
FUNCTION_URL=$(gcloud functions describe image-analyzer --region="$REGION" --format="value(serviceConfig.uri)" 2>/dev/null || echo "Not deployed")
WORKER_URL=$(gcloud run services describe image-analyzer-worker --region="$REGION" --format="value(status.url)" 2>/dev/null || echo "Not deployed")

echo "📡 Deployed Services Summary:"
echo "   Server (Cloud Function): $FUNCTION_URL"
echo "   Worker (Cloud Run):      $WORKER_URL"
echo ""

echo "🧪 Complete system test commands:"
echo ""
echo "# 1. Health checks:"
echo "curl \"$FUNCTION_URL/api/v1/health\""
echo "curl \"$WORKER_URL/health\""
echo ""
echo "# 2. Upload test batch:"
echo "curl -X POST -F \"file=@test_batch.csv\" -F \"batch_name=Test\" \"$FUNCTION_URL/api/v1/batches\""
echo ""
echo "# 3. Trigger worker manually:"
echo "curl -X POST \"$WORKER_URL/process\" -H \"Content-Type: application/json\" -d '{\"trigger\": \"manual\"}'"
echo ""
echo "# 4. Check batch status:"
echo "curl \"$FUNCTION_URL/api/v1/batches\""
echo ""

echo "📊 Monitor both services:"
echo "gcloud functions logs read image-analyzer --region=$REGION --limit=20"
echo "gcloud run logs read image-analyzer-worker --region=$REGION --limit=20"
echo ""

echo "🔧 System management:"
echo "# Scale down workers:"
echo "gcloud run services update image-analyzer-worker --region=$REGION --max-instances=1"
echo ""
echo "# Scale up workers:"
echo "gcloud run services update image-analyzer-worker --region=$REGION --max-instances=10"
echo ""
echo "# Check scheduler status:"
echo "gcloud scheduler jobs describe worker-trigger --location=$REGION"