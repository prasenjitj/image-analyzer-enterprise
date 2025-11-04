#!/bin/bash

# Enhanced script to build and deploy the main server application to Google Cloud Run
# Features: Interactive prompts, rich terminal UI, progress indicators, error handling
# Usage: ./build_and_deploy_server.sh [PROJECT_ID] [REGION]

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

# Spinner function for progress indication
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# Progress bar function
progress_bar() {
    local current=$1
    local total=$2
    local width=50
    local percentage=$((current * 100 / total))
    local completed=$((current * width / total))

    printf "\r["
    for ((i=1; i<=completed; i++)); do printf "="; done
    for ((i=completed+1; i<=width; i++)); do printf " "; done
    printf "] %d%%" $percentage
}

# Print formatted header
print_header() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                    🚀 SERVER DEPLOYMENT TO GOOGLE CLOUD RUN${CYAN}                    ║${NC}"
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
    REGION="${2:-us-central1}"
    VPC_CONNECTOR="${3:-image-analyzer-connector}"

    # Display configuration
    echo -e "${WHITE}📋 Deployment Configuration:${NC}"
    echo -e "   ${CYAN}Project ID:${NC}     $PROJECT_ID"
    echo -e "   ${CYAN}Region:${NC}         $REGION"
    echo -e "   ${CYAN}VPC Connector:${NC} $VPC_CONNECTOR"
    echo ""

    # Confirm deployment
    confirm_action "Ready to deploy server to Google Cloud Run?"

    # Step 1: Set GCP project
    print_section "Setting GCP Project" "📋"
    echo -e "${WHITE}Setting project to ${CYAN}$PROJECT_ID${WHITE}...${NC}"

    if gcloud config set project "$PROJECT_ID" > /dev/null 2>&1; then
        print_success "GCP project set successfully"
    else
        print_error "Failed to set GCP project"
        exit 1
    fi
    echo ""

    # Step 2: Build application image
    print_section "Building Application Image" "🔨"
    echo -e "${WHITE}Building Docker image...${NC}"

    cd "$(dirname "$0")/.." # Go to project root

    # Start build process
    gcloud builds submit --tag "gcr.io/$PROJECT_ID/image-analyzer:latest" . > /tmp/build_output.log 2>&1 &
    local build_pid=$!

    # Show progress while building
    echo -e "${YELLOW}Building image (this may take several minutes)...${NC}"
    spinner $build_pid

    # Check if build succeeded
    if wait $build_pid; then
        print_success "Docker image built successfully"
        echo -e "   ${CYAN}Image:${NC} gcr.io/$PROJECT_ID/image-analyzer:latest"
    else
        print_error "Docker image build failed"
        echo -e "${RED}Build output:${NC}"
        cat /tmp/build_output.log
        exit 1
    fi
    echo ""

    # Step 3: Deploy to Cloud Run
    print_section "Deploying to Cloud Run" "🚀"
    echo -e "${WHITE}Deploying to Google Cloud Run...${NC}"
    echo -e "${YELLOW}Deployment in progress (this may take 2-3 minutes)...${NC}"

    # Cloud Run deployment
    if gcloud run deploy image-analyzer \
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
        --env-vars-file=.env.yaml > /tmp/deploy_output.log 2>&1; then

        print_success "Cloud Run deployment completed successfully"
    else
        print_error "Cloud Run deployment failed"
        echo -e "${RED}Deployment output:${NC}"
        cat /tmp/deploy_output.log
        exit 1
    fi
    echo ""

    # Step 4: Get deployment info
    print_section "Deployment Information" "📡"
    SERVICE_URL=$(gcloud run services describe image-analyzer --region="$REGION" --format="value(status.url)" 2>/dev/null)

    if [ -n "$SERVICE_URL" ]; then
        print_success "Service deployed successfully"
        echo -e "   ${CYAN}Service URL:${NC} $SERVICE_URL"
        echo -e "   ${CYAN}Region:${NC}      $REGION"
        echo -e "   ${CYAN}Memory:${NC}      4Gi"
        echo -e "   ${CYAN}CPU:${NC}         2 cores"
        echo -e "   ${CYAN}Max instances:${NC} 50"
        echo -e "   ${CYAN}Min instances:${NC} 2"
    else
        print_warning "Could not retrieve service URL"
    fi
    echo ""

    # Step 5: Update environment
    print_section "Updating Environment" "🔧"
    echo -e "${WHITE}Updating .env.yaml with server URL...${NC}"

    if [ -n "$SERVICE_URL" ]; then
        if grep -q "SERVER_URL" .env.yaml 2>/dev/null; then
            # Replace existing SERVER_URL
            sed -i.bak "s|SERVER_URL:.*|SERVER_URL: \"$SERVICE_URL\"|" .env.yaml
            print_success "Updated existing SERVER_URL in .env.yaml"
        else
            # Add SERVER_URL to .env.yaml
            echo "SERVER_URL: \"$SERVICE_URL\"" >> .env.yaml
            print_success "Added SERVER_URL to .env.yaml"
        fi
    else
        print_warning "Skipping environment update (no service URL available)"
    fi
    echo ""

    # Calculate deployment time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))

    # Final summary
    print_section "Deployment Summary" "🎉"
    print_success "Server deployment completed successfully!"
    echo -e "   ${CYAN}⏱️  Total time:${NC}  ${minutes}m ${seconds}s"
    echo -e "   ${CYAN}🌐 Service URL:${NC} $SERVICE_URL"
    echo -e "   ${CYAN}📍 Region:${NC}      $REGION"
    echo ""

    # Testing instructions
    print_section "Testing Instructions" "🧪"
    echo -e "${WHITE}Test your deployment:${NC}"
    echo ""
    echo -e "${CYAN}# Health check:${NC}"
    echo -e "curl \"$SERVICE_URL/api/v1/health\""
    echo ""
    echo -e "${CYAN}# Upload test batch:${NC}"
    echo -e "curl -X POST -F \"file=@test_batch.csv\" -F \"batch_name=Test\" \"$SERVICE_URL/api/v1/batches\""
    echo ""
    echo -e "${CYAN}# Check batches:${NC}"
    echo -e "curl \"$SERVICE_URL/api/v1/batches\""
    echo ""
    echo -e "${CYAN}# Admin dashboard:${NC}"
    echo -e "curl \"$SERVICE_URL/admin/dashboard\""
    echo ""

    # Monitoring instructions
    print_section "Monitoring & Next Steps" "📊"
    echo -e "${WHITE}Monitor Cloud Run logs:${NC}"
    echo -e "${CYAN}gcloud run services logs read image-analyzer --region=$REGION --limit=500${NC}"
    echo ""
    echo -e "${WHITE}Next steps:${NC}"
    echo -e "${GREEN}1.${NC} Deploy workers: ${CYAN}./scripts/build_and_deploy_worker.sh${NC}"
    echo -e "${GREEN}2.${NC} Test end-to-end functionality"
    echo -e "${GREEN}3.${NC} Configure monitoring and alerts"
    echo ""

    # Cleanup
    rm -f /tmp/build_output.log /tmp/deploy_output.log 2>/dev/null

    print_success "🎉 Deployment completed successfully!"
}

# Run main function
main "$@"