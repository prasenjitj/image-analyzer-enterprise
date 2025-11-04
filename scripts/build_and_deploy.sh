#!/bin/bash

# Enhanced script to build and deploy the complete image analyzer system to Google Cloud
# Features: Interactive prompts, rich terminal UI, progress indicators, error handling
# This is a combined deployment script that calls individual server and worker scripts
# Usage: ./build_and_deploy.sh [PROJECT_ID] [REGION] [VPC_CONNECTOR]

set -e

# Color codes for rich terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Print formatted header
print_header() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}              🚀 COMPLETE SYSTEM DEPLOYMENT TO GOOGLE CLOUD${CYAN}                 ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Print section header
print_section() {
    local title="$1"
    local icon="$2"
    echo -e "${BLUE}┌─────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${BLUE}│${WHITE} ${icon} ${title}${BLUE}$(printf ' %.0s' {1..$((${#title} + 3))})${BLUE}│${NC}"
    echo -e "${BLUE}└─────────────────────────────────────────────────────────────────────────────┘${NC}"
}

# Print success message
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

# Print error message
print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Print warning message
print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Print info message
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Interactive confirmation
confirm_action() {
    local message="$1"
    echo -e "${YELLOW}${message}${NC}"
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}Deployment cancelled by user.${NC}"
        exit 1
    fi
}

# Main deployment function
main() {
    local start_time=$(date +%s)

    # Print header
    print_header

    # Parse arguments with defaults
    PROJECT_ID="${1:-ops-excellence}"
    REGION="${2:-asia-south2}"
    VPC_CONNECTOR="${3:-image-analyzer-connector}"

    # Display configuration
    echo -e "${WHITE}📋 Complete System Deployment Configuration:${NC}"
    echo -e "   ${CYAN}Project ID:${NC}     $PROJECT_ID"
    echo -e "   ${CYAN}Region:${NC}         $REGION"
    echo -e "   ${CYAN}VPC Connector:${NC} $VPC_CONNECTOR"
    echo ""

    # Confirm deployment
    confirm_action "Ready to deploy complete system (server + worker) to Google Cloud?"

    # Get the directory where this script is located
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Step 1: Deploy server
    print_section "Deploying Server Component" "🖥️"
    echo -e "${WHITE}Starting server deployment...${NC}"
    echo ""

    if "$SCRIPT_DIR/build_and_deploy_server.sh" "$PROJECT_ID" "$REGION" "$VPC_CONNECTOR"; then
        print_success "Server deployment completed successfully"
    else
        print_error "Server deployment failed"
        exit 1
    fi
    echo ""

    # Step 2: Deploy worker
    print_section "Deploying Worker Component" "⚙️"
    echo -e "${WHITE}Starting worker deployment...${NC}"
    echo ""

    if "$SCRIPT_DIR/build_and_deploy_worker.sh" "$PROJECT_ID" "$REGION" "$VPC_CONNECTOR"; then
        print_success "Worker deployment completed successfully"
    else
        print_error "Worker deployment failed"
        exit 1
    fi
    echo ""

    # Calculate deployment time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))

    # Step 3: Get deployment information
    print_section "Deployment Information" "📡"
    SERVER_URL=$(gcloud run services describe image-analyzer --region="$REGION" --format="value(status.url)" 2>/dev/null || echo "Not available")
    WORKER_URL=$(gcloud run services describe image-analyzer-worker --region="$REGION" --format="value(status.url)" 2>/dev/null || echo "Not available")

    print_success "System deployment completed successfully!"
    echo -e "   ${CYAN}⏱️  Total time:${NC}  ${minutes}m ${seconds}s"
    echo -e "   ${CYAN}🖥️  Server URL:${NC}  $SERVER_URL"
    echo -e "   ${CYAN}⚙️  Worker URL:${NC}  $WORKER_URL"
    echo -e "   ${CYAN}📍 Region:${NC}      $REGION"
    echo ""

    # Testing instructions
    print_section "System Testing Instructions" "🧪"
    echo -e "${WHITE}Test your complete deployment:${NC}"
    echo ""
    echo -e "${CYAN}# 1. Health checks:${NC}"
    echo -e "curl \"$SERVER_URL/api/v1/health\""
    echo -e "curl \"$WORKER_URL/health\""
    echo ""
    echo -e "${CYAN}# 2. Upload test batch:${NC}"
    echo -e "curl -X POST -F \"file=@test_batch.csv\" -F \"batch_name=Test\" \"$SERVER_URL/api/v1/batches\""
    echo ""
    echo -e "${CYAN}# 3. Check batch status:${NC}"
    echo -e "curl \"$SERVER_URL/api/v1/batches\""
    echo ""
    echo -e "${CYAN}# 4. Trigger worker manually:${NC}"
    echo -e "curl -X POST \"$WORKER_URL/process\" -H \"Content-Type: application/json\" -d '{\"trigger\": \"manual\"}'"
    echo ""

    # Monitoring instructions
    print_section "Monitoring & Management" "📊"
    echo -e "${WHITE}Monitor your services:${NC}"
    echo -e "${CYAN}gcloud run services logs read image-analyzer --region=$REGION --limit=20${NC}"
    echo -e "${CYAN}gcloud run services logs read image-analyzer-worker --region=$REGION --limit=20${NC}"
    echo ""
    echo -e "${WHITE}System management commands:${NC}"
    echo -e "${GREEN}# Scale down workers:${NC}"
    echo -e "gcloud run services update image-analyzer-worker --region=$REGION --max-instances=1"
    echo ""
    echo -e "${GREEN}# Scale up workers:${NC}"
    echo -e "gcloud run services update image-analyzer-worker --region=$REGION --max-instances=10"
    echo ""
    echo -e "${GREEN}# Check scheduler status:${NC}"
    echo -e "gcloud scheduler jobs describe worker-trigger --location=$REGION"
    echo ""

    print_success "🎉 Complete system deployment finished successfully!"
}

# Run main function
main "$@"