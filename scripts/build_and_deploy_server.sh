#!/bin/bash

# Script to build and deploy the main server application to Google Cloud Run
# Usage: ./build_and_deploy_server.sh [PROJECT_ID] [REGION]

set -e

PROJECT_ID="${1:-ops-excellence}"
REGION="${2:-us-central1}"
VPC_CONNECTOR="${3:-image-analyzer-connector}"

echo "🚀 Starting server build and deployment..."
echo "   Project ID: $PROJECT_ID"
echo "   Region: $REGION"
echo "   VPC Connector: $VPC_CONNECTOR"

# Set the project
echo "📋 Setting GCP project..."
gcloud config set project "$PROJECT_ID"

# Build main application image
echo "🔨 Building main application image..."
cd "$(dirname "$0")/.." # Go to project root
gcloud builds submit --tag "gcr.io/$PROJECT_ID/image-analyzer:latest" .

# Deploy main application as Cloud Run service
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy image-analyzer \
    --image="gcr.io/$PROJECT_ID/image-analyzer:latest" \
    --region="$REGION" \
    --platform=managed \
    --allow-unauthenticated \
    --memory=4Gi \
    --cpu=2 \
    --timeout=3600s \
    --max-instances=50 \
    --min-instances=2 \
    --concurrency=100 \
    --port=8080 \
    --vpc-connector="$VPC_CONNECTOR" \
    --vpc-egress=private-ranges-only \
    --ingress=all \
    --execution-environment=gen2 \
    --env-vars-file=.env.yaml

# Get the deployed URL
echo ""
echo "🎉 Cloud Run deployment completed!"
echo ""
SERVICE_URL=$(gcloud run services describe image-analyzer --region="$REGION" --format="value(status.url)")

echo "📡 Deployed Server:"
echo "   Main App: $SERVICE_URL"
echo ""

# Update server URL in environment if needed
echo "🔧 Updating server URL in environment..."
if grep -q "SERVER_URL" .env.yaml; then
    # Replace existing SERVER_URL
    sed -i.bak "s|SERVER_URL:.*|SERVER_URL: \"$SERVICE_URL\"|" .env.yaml
else
    # Add SERVER_URL to .env.yaml
    echo "SERVER_URL: \"$SERVICE_URL\"" >> .env.yaml
fi

echo "✅ Environment updated with server URL"
echo ""

# Provide testing instructions
echo "🧪 Test your Cloud Run deployment:"
echo ""
echo "# Health check:"
echo "curl \"$SERVICE_URL/api/v1/health\""
echo ""
echo "# Upload test batch:"
echo "curl -X POST -F \"file=@test_batch.csv\" -F \"batch_name=Test\" \"$SERVICE_URL/api/v1/batches\""
echo ""
echo "# Check batches:"
echo "curl \"$SERVICE_URL/api/v1/batches\""
echo ""
echo "# Admin dashboard:"
echo "curl \"$SERVICE_URL/admin/dashboard\""
echo ""

echo "📊 Monitor Cloud Run logs:"
echo "gcloud run services logs read image-analyzer --region=us-central1 --limit=500"
echo ""

echo "🔧 Next steps:"
echo "1. Deploy workers: ./scripts/build_and_deploy_worker.sh"
echo "2. Test end-to-end functionality"
echo "3. Configure monitoring and alerts"