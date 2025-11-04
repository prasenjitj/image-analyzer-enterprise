#!/bin/bash

# Script to build and deploy the background worker to Google Cloud Run
# Usage: ./build_and_deploy_worker.sh [PROJECT_ID] [REGION]

set -e

PROJECT_ID="${1:-ops-excellence}"
REGION="${2:-us-central1}"
VPC_CONNECTOR="${3:-image-analyzer-connector}"

echo "🚀 Starting worker build and deployment..."
echo "   Project ID: $PROJECT_ID"
echo "   Region: $REGION"
echo "   VPC Connector: $VPC_CONNECTOR"

# Set the project
echo "📋 Setting GCP project..."
gcloud config set project "$PROJECT_ID"

# Build worker image
echo "🔨 Building worker image..."
cd "$(dirname "$0")/.." # Go to project root

# Create a temporary cloudbuild.yaml for the worker
cat > cloudbuild-worker.yaml <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-f', 'Dockerfile.worker', '-t', 'gcr.io/$PROJECT_ID/image-analyzer-worker:latest', '.']
images: ['gcr.io/$PROJECT_ID/image-analyzer-worker:latest']
EOF

gcloud builds submit --config=cloudbuild-worker.yaml .

# Clean up temporary file
rm cloudbuild-worker.yaml

# Deploy background worker as Cloud Run
echo "🏃 Deploying background worker..."
gcloud run deploy image-analyzer-worker \
    --image="gcr.io/$PROJECT_ID/image-analyzer-worker:latest" \
    --region="$REGION" \
    --platform=managed \
    --allow-unauthenticated \
    --memory=2Gi \
    --cpu=2 \
    --env-vars-file=.env.yaml \
    --max-instances=5 \
    --concurrency=10 \
    --vpc-connector="$VPC_CONNECTOR"

# Get the deployed URL
echo ""
echo "🎉 Worker deployment completed!"
echo ""
WORKER_URL=$(gcloud run services describe image-analyzer-worker --region="$REGION" --format="value(status.url)")

echo "📡 Deployed Worker:"
echo "   Worker Service: $WORKER_URL"
echo ""

# Update worker URL in environment if needed
echo "🔧 Updating worker URL in environment..."
if grep -q "WORKER_URL" .env.yaml; then
    # Replace existing WORKER_URL
    sed -i.bak "s|WORKER_URL:.*|WORKER_URL: \"$WORKER_URL\"|" .env.yaml
else
    # Add WORKER_URL to .env.yaml
    echo "WORKER_URL: \"$WORKER_URL\"" >> .env.yaml
fi

echo "✅ Environment updated with worker URL"
echo ""

# Set up Cloud Scheduler for automatic worker triggering (optional)
echo "🕒 Setting up Cloud Scheduler for worker automation..."

# Check if scheduler job already exists
if gcloud scheduler jobs describe worker-trigger --location="$REGION" &>/dev/null; then
    echo "⚠️  Scheduler job 'worker-trigger' already exists. Updating..."
    gcloud scheduler jobs update http worker-trigger \
        --location="$REGION" \
        --schedule="*/2 * * * *" \
        --uri="$WORKER_URL/process" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"trigger": "scheduled"}'
else
    echo "📅 Creating new scheduler job..."
    gcloud scheduler jobs create http worker-trigger \
        --location="$REGION" \
        --schedule="*/2 * * * *" \
        --uri="$WORKER_URL/process" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"trigger": "scheduled"}' \
        --description="Triggers image analysis worker every 2 minutes"
fi

echo "✅ Worker automation configured"
echo ""

# Provide testing instructions
echo "🧪 Test your worker deployment:"
echo ""
echo "# Manual worker trigger:"
echo "curl -X POST \"$WORKER_URL/process\" -H \"Content-Type: application/json\" -d '{\"trigger\": \"manual\"}'"
echo ""
echo "# Worker health check:"
echo "curl \"$WORKER_URL/health\""
echo ""
echo "# Worker status:"
echo "curl \"$WORKER_URL/status\""
echo ""

echo "📊 Monitor worker logs:"
echo "gcloud run services logs read image-analyzer-worker --region=$REGION --limit=50"
echo ""

echo "🕒 Monitor scheduler:"
echo "gcloud scheduler jobs describe worker-trigger --location=$REGION"
echo "gcloud scheduler jobs run worker-trigger --location=$REGION"
echo ""

echo "🔧 Next steps:"
echo "1. Test worker processing with sample batch"
echo "2. Monitor worker performance and scaling"
echo "3. Adjust scheduler frequency if needed"
echo "4. Set up monitoring alerts for worker failures"