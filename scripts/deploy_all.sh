#!/bin/bash

# Master deployment script that runs all steps in sequence
# Usage: ./deploy_all.sh [VM_IP] [PROJECT_ID] [REGION]

set -e

# Default values (update these for your environment)
VM_IP="${1}"
PROJECT_ID="${2}"
REGION="${3:-us-central1}"

# Check if required parameters are provided
if [ -z "$VM_IP" ] || [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: Please provide VM_IP and PROJECT_ID as parameters"
    echo "Usage: $0 <VM_IP> <PROJECT_ID> [REGION]"
    echo ""
    echo "Example: $0 10.10.0.2 my-gcp-project us-central1"
    echo ""
    echo "Parameters:"
    echo "  VM_IP: IP address of your VM hosting PostgreSQL and Redis"
    echo "  PROJECT_ID: Your Google Cloud Project ID"
    echo "  REGION: GCP region for deployment (default: us-central1)"
    exit 1
fi

echo "🚀 Starting complete GCP deployment..."
echo ""
echo "Configuration:"
echo "  VM IP: $VM_IP"
echo "  PostgreSQL Port: 5432"
echo "  Redis Port: 6379"
echo "  Project ID: $PROJECT_ID"
echo "  Region: $REGION"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root directory
cd "$PROJECT_ROOT"

# Step 1: Create environment variables
echo "📝 Step 1: Creating environment variables..."
"$SCRIPT_DIR/create_env_yaml.sh" "$VM_IP" "$PROJECT_ID"

# Step 2: Create Dockerfiles
echo ""
echo "🐳 Step 2: Creating Dockerfiles..."
"$SCRIPT_DIR/create_dockerfiles.sh"

# Step 3: Set up VPC connector
echo ""
echo "🔗 Step 3: Setting up VPC connector..."
"$SCRIPT_DIR/setup_vpc_connector.sh" "$PROJECT_ID" "$REGION"

# Step 4: Build and deploy
echo ""
echo "🚀 Step 4: Building and deploying..."
"$SCRIPT_DIR/build_and_deploy.sh" "$PROJECT_ID" "$REGION"

echo ""
echo "🎉 All deployment steps completed successfully!"
echo ""
echo "Next steps:"
echo "1. Test the deployment using the provided curl commands"
echo "2. Monitor logs: gcloud functions logs read image-analyzer --region $REGION"
echo "3. Check VM status: gcloud compute ssh YOUR_VM_NAME --zone YOUR_ZONE --project $PROJECT_ID --command 'sudo systemctl status postgresql redis-server'"
echo ""
echo "⚠️  Remember to:"
echo "1. Edit .env.yaml with your actual credentials"
echo "2. Configure your VM firewall rules"
echo "3. Set up monitoring and alerts"