#!/bin/bash

# Script to set up firewall rules for single VM (pj-vm) deployment
# This VM hosts both PostgreSQL and Redis
# Usage: ./setup_firewall_rules.sh [PROJECT_ID]

set -e

# Default values
PROJECT_ID="${1:-ops-excellence}"
VM_NAME="pj-vm"
VM_ZONE="asia-south2-c"
NETWORK="image-analyzer-vpc"
VPC_CONNECTOR_RANGE="10.8.0.0/28"

echo "Setting up firewall rules for single VM deployment..."
echo ""
echo "Configuration:"
echo "  Project ID: $PROJECT_ID"
echo "  VM Name: $VM_NAME"
echo "  VM Zone: $VM_ZONE"
echo "  Network: $NETWORK"
echo "  VPC Connector Range: $VPC_CONNECTOR_RANGE"
echo ""

# Function to create or update firewall rule
create_or_update_firewall_rule() {
  local rule_name=$1
  local description=$2
  local allow=$3
  local tags=$4
  
  if gcloud compute firewall-rules describe "$rule_name" --project="$PROJECT_ID" &>/dev/null; then
    echo "⚠️  Firewall rule '$rule_name' already exists. Updating..."
    gcloud compute firewall-rules update "$rule_name" \
      --project="$PROJECT_ID" \
      --priority=1000 \
      --allow="$allow" \
      --source-ranges="$VPC_CONNECTOR_RANGE" \
      --target-tags="$tags"
  else
    echo "Creating firewall rule '$rule_name'..."
    gcloud compute firewall-rules create "$rule_name" \
      --project="$PROJECT_ID" \
      --network="$NETWORK" \
      --priority=1000 \
      --direction=INGRESS \
      --action=ALLOW \
      --allow="$allow" \
      --source-ranges="$VPC_CONNECTOR_RANGE" \
      --target-tags="$tags" \
      --description="$description"
  fi
  echo "✅ Firewall rule '$rule_name' configured successfully!"
  echo ""
}

# Create/update PostgreSQL firewall rule
create_or_update_firewall_rule \
  "allow-postgres-from-serverless" \
  "Allow PostgreSQL access from VPC Connector to pj-vm" \
  "tcp:5432" \
  "postgres"

# Create/update Redis firewall rule
create_or_update_firewall_rule \
  "allow-redis-from-serverless" \
  "Allow Redis access from VPC Connector to pj-vm" \
  "tcp:6379" \
  "redis"

# Ensure SSH rule has correct priority
echo "Updating SSH firewall rule priority..."
if gcloud compute firewall-rules describe allow-ssh-from-tcp --project="$PROJECT_ID" &>/dev/null; then
  gcloud compute firewall-rules update allow-ssh-from-tcp \
    --project="$PROJECT_ID" \
    --priority=1000
  echo "✅ SSH firewall rule priority updated to 1000"
else
  echo "⚠️  SSH firewall rule 'allow-ssh-from-tcp' not found. Creating..."
  gcloud compute firewall-rules create allow-ssh-from-tcp \
    --project="$PROJECT_ID" \
    --network="$NETWORK" \
    --priority=1000 \
    --direction=INGRESS \
    --action=ALLOW \
    --allow=tcp:22,udp,icmp \
    --source-ranges=0.0.0.0/0 \
    --description="Allow SSH access to VMs"
  echo "✅ SSH firewall rule created"
fi

echo ""
echo "Updating VM tags..."

# Add postgres and redis tags to pj-vm
gcloud compute instances add-tags "$VM_NAME" \
  --zone="$VM_ZONE" \
  --project="$PROJECT_ID" \
  --tags=postgres,redis

echo "✅ VM tags updated successfully!"
echo ""

# Display current tags
echo "Current VM tags:"
gcloud compute instances describe "$VM_NAME" \
  --zone="$VM_ZONE" \
  --project="$PROJECT_ID" \
  --format="value(tags.items)"

echo ""
echo "Firewall rules summary:"
gcloud compute firewall-rules list \
  --project="$PROJECT_ID" \
  --filter="name:(allow-postgres-from-serverless OR allow-redis-from-serverless OR allow-ssh-from-tcp)" \
  --format="table(name,network,priority,sourceRanges.list():label=SOURCE,allowed[].map().firewall_rule().list():label=ALLOW,targetTags.list():label=TAGS)"

echo ""
echo "✅ All firewall rules configured successfully!"
echo ""
echo "To verify connectivity:"
echo "  1. SSH: gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID"
echo "  2. PostgreSQL: From Cloud Functions/Cloud Run via VPC Connector"
echo "  3. Redis: From Cloud Functions/Cloud Run via VPC Connector"
