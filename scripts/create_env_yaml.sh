#!/bin/bash

# Script to create/update .env.yaml file with proper configuration
# Usage: ./create_env_yaml.sh [VM_IP] [PROJECT_ID]

set -e

VM_IP="${1:-YOUR_VM_IP}"
PROJECT_ID="${2:-YOUR_PROJECT_ID}"

# Check if required parameters are provided
if [ "$VM_IP" = "YOUR_VM_IP" ] || [ "$PROJECT_ID" = "YOUR_PROJECT_ID" ]; then
    echo "❌ Error: Please provide VM_IP and PROJECT_ID as parameters"
    echo "Usage: $0 <VM_IP> <PROJECT_ID>"
    echo ""
    echo "Example: $0 10.10.0.2 my-gcp-project"
    exit 1
fi

echo "📝 Creating environment configuration..."

# Create .env.yaml file
cat > .env.yaml << EOF
DATABASE_URL: "postgresql://YOUR_DB_USER:YOUR_DB_PASSWORD@${VM_IP}:5432/imageprocessing"
REDIS_URL: "redis://:YOUR_REDIS_PASSWORD@${VM_IP}:6379/0"
GOOGLE_API_KEY: "YOUR_GOOGLE_API_KEY"
SECRET_KEY: "YOUR_SECRET_KEY_HERE"
UPLOAD_BUCKET: "gs://YOUR_PROJECT_BUCKET_UPLOADS"
EXPORT_BUCKET: "gs://YOUR_PROJECT_BUCKET_EXPORTS"
MAX_UPLOAD_SIZE: "104857600"
CHUNK_SIZE: "1000"
MAX_CONCURRENT_BATCHES: "10"
REQUESTS_PER_MINUTE: "55"
EOF

echo "✅ Environment configuration template created in .env.yaml"
echo "   - VM IP: ${VM_IP}"
echo "   - Project ID: ${PROJECT_ID}"
echo ""
echo "⚠️  IMPORTANT: Please edit .env.yaml and replace the following placeholders:"
echo "   - YOUR_DB_USER: Database username"
echo "   - YOUR_DB_PASSWORD: Database password"  
echo "   - YOUR_REDIS_PASSWORD: Redis password (or remove if no password)"
echo "   - YOUR_GOOGLE_API_KEY: Your Google Vision API key"
echo "   - YOUR_SECRET_KEY_HERE: Flask secret key"
echo "   - YOUR_PROJECT_BUCKET_*: Your GCS bucket names"