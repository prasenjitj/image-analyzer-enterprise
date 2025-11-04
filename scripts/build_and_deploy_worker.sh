#!/bin/bash

# Enhanced script to build and deploy the background worker to Google Cloud Run
# Features: Interactive prompts, rich terminal UI, progress indicators, error handling
# Usage: ./build_and_deploy_worker.sh [PROJECT_ID] [REGION]

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

# Print formatted header
print_header() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                  🚀 WORKER DEPLOYMENT TO GOOGLE CLOUD RUN${CYAN}                   ║${NC}"
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
    echo -e "${WHITE}� Worker Deployment Configuration:${NC}"
    echo -e "   ${CYAN}Project ID:${NC}     $PROJECT_ID"
    echo -e "   ${CYAN}Region:${NC}         $REGION"
    echo -e "   ${CYAN}VPC Connector:${NC} $VPC_CONNECTOR"
    echo ""

    # Confirm deployment
    confirm_action "Ready to deploy worker to Google Cloud Run?"

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

    # Step 2: Build worker image
    print_section "Building Worker Image" "🔨"
    echo -e "${WHITE}Building Docker image for worker...${NC}"

    cd "$(dirname "$0")/.." # Go to project root

    # Create a temporary cloudbuild.yaml for the worker
    cat > cloudbuild-worker.yaml <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-f', 'Dockerfile.worker', '-t', 'gcr.io/$PROJECT_ID/image-analyzer-worker:latest', '.']
images: ['gcr.io/$PROJECT_ID/image-analyzer-worker:latest']
EOF

    # Start build process
    gcloud builds submit --config=cloudbuild-worker.yaml . > /tmp/worker_build_output.log 2>&1 &
    local build_pid=$!

    # Show progress while building
    echo -e "${YELLOW}Building worker image (this may take several minutes)...${NC}"
    spinner $build_pid

    # Check if build succeeded
    if wait $build_pid; then
        print_success "Worker Docker image built successfully"
        echo -e "   ${CYAN}Image:${NC} gcr.io/$PROJECT_ID/image-analyzer-worker:latest"
    else
        print_error "Worker image build failed"
        echo -e "${RED}Build output:${NC}"
        cat /tmp/worker_build_output.log
        rm -f cloudbuild-worker.yaml
        exit 1
    fi

    # Clean up temporary file
    rm -f cloudbuild-worker.yaml
    echo ""

    # Step 3: Deploy background worker
    print_section "Deploying Worker to Cloud Run" "🏃"
    echo -e "${WHITE}Deploying background worker...${NC}"
    echo -e "${YELLOW}Deployment in progress (this may take 2-3 minutes)...${NC}"

    # Cloud Run deployment
    if gcloud run deploy image-analyzer-worker \
        --image="gcr.io/$PROJECT_ID/image-analyzer-worker:latest" \
        --region="$REGION" \
        --platform=managed \
        --allow-unauthenticated \
        --memory=2Gi \
        --cpu=2 \
        --env-vars-file=.env.yaml \
        --max-instances=50 \
        --concurrency=100 \
        --vpc-connector="$VPC_CONNECTOR" > /tmp/worker_deploy_output.log 2>&1; then

        print_success "Worker deployment completed successfully"
    else
        print_error "Worker deployment failed"
        echo -e "${RED}Deployment output:${NC}"
        cat /tmp/worker_deploy_output.log
        exit 1
    fi
    echo ""

    # Step 4: Get deployment info
    print_section "Worker Deployment Information" "📡"
    WORKER_URL=$(gcloud run services describe image-analyzer-worker --region="$REGION" --format="value(status.url)" 2>/dev/null)

    if [ -n "$WORKER_URL" ]; then
        print_success "Worker service deployed successfully"
        echo -e "   ${CYAN}Service URL:${NC} $WORKER_URL"
        echo -e "   ${CYAN}Region:${NC}      $REGION"
        echo -e "   ${CYAN}Memory:${NC}      2Gi"
        echo -e "   ${CYAN}CPU:${NC}         2 cores"
        echo -e "   ${CYAN}Max instances:${NC} 5"
    else
        print_warning "Could not retrieve worker service URL"
    fi
    echo ""

    # Step 5: Update environment
    print_section "Updating Environment" "🔧"
    echo -e "${WHITE}Updating .env.yaml with worker URL...${NC}"

    if [ -n "$WORKER_URL" ]; then
        if grep -q "WORKER_URL" .env.yaml 2>/dev/null; then
            # Replace existing WORKER_URL
            sed -i.bak "s|WORKER_URL:.*|WORKER_URL: \"$WORKER_URL\"|" .env.yaml
            print_success "Updated existing WORKER_URL in .env.yaml"
        else
            # Add WORKER_URL to .env.yaml
            echo "WORKER_URL: \"$WORKER_URL\"" >> .env.yaml
            print_success "Added WORKER_URL to .env.yaml"
        fi
    else
        print_warning "Skipping environment update (no worker URL available)"
    fi
    echo ""

    # Step 6: Set up Cloud Scheduler
    print_section "Configuring Automation" "🕒"
    echo -e "${WHITE}Setting up Cloud Scheduler for worker automation...${NC}"

    # Check if scheduler job already exists
    if gcloud scheduler jobs describe worker-trigger --location="$REGION" &>/dev/null; then
        echo -e "${YELLOW}Scheduler job 'worker-trigger' already exists. Updating...${NC}"
        if gcloud scheduler jobs update http worker-trigger \
            --location="$REGION" \
            --schedule="*/2 * * * *" \
            --uri="$WORKER_URL/process" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --message-body='{"trigger": "scheduled"}' > /dev/null 2>&1; then
            print_success "Scheduler job updated successfully"
        else
            print_warning "Failed to update scheduler job"
        fi
    else
        echo -e "${WHITE}Creating new scheduler job...${NC}"
        if gcloud scheduler jobs create http worker-trigger \
            --location="$REGION" \
            --schedule="*/2 * * * *" \
            --uri="$WORKER_URL/process" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --message-body='{"trigger": "scheduled"}' \
            --description="Triggers image analysis worker every 2 minutes" > /dev/null 2>&1; then
            print_success "Scheduler job created successfully"
        else
            print_warning "Failed to create scheduler job"
        fi
    fi
    echo ""

    # Calculate deployment time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))

    # Final summary
    print_section "Worker Deployment Summary" "🎉"
    print_success "Worker deployment completed successfully!"
    echo -e "   ${CYAN}⏱️  Total time:${NC}  ${minutes}m ${seconds}s"
    echo -e "   ${CYAN}🏃 Worker URL:${NC} $WORKER_URL"
    echo -e "   ${CYAN}📍 Region:${NC}      $REGION"
    echo -e "   ${CYAN}🕒 Schedule:${NC}   Every 2 minutes"
    echo ""

    # Testing instructions
    print_section "Worker Testing Instructions" "🧪"
    echo -e "${WHITE}Test your worker deployment:${NC}"
    echo ""
    echo -e "${CYAN}# Manual worker trigger:${NC}"
    echo -e "curl -X POST \"$WORKER_URL/process\" -H \"Content-Type: application/json\" -d '{\"trigger\": \"manual\"}'"
    echo ""
    echo -e "${CYAN}# Worker health check:${NC}"
    echo -e "curl \"$WORKER_URL/health\""
    echo ""
    echo -e "${CYAN}# Worker status:${NC}"
    echo -e "curl \"$WORKER_URL/status\""
    echo ""

    # Monitoring instructions
    print_section "Monitoring & Management" "📊"
    echo -e "${WHITE}Monitor worker service:${NC}"
    echo -e "${CYAN}gcloud run services logs read image-analyzer-worker --region=$REGION --limit=50${NC}"
    echo ""
    echo -e "${WHITE}Monitor scheduler:${NC}"
    echo -e "${CYAN}gcloud scheduler jobs describe worker-trigger --location=$REGION${NC}"
    echo -e "${CYAN}gcloud scheduler jobs run worker-trigger --location=$REGION${NC}"
    echo ""
    echo -e "${WHITE}Worker management:${NC}"
    echo -e "${GREEN}# Scale down workers:${NC}"
    echo -e "gcloud run services update image-analyzer-worker --region=$REGION --max-instances=1"
    echo ""
    echo -e "${GREEN}# Scale up workers:${NC}"
    echo -e "gcloud run services update image-analyzer-worker --region=$REGION --max-instances=10"
    echo ""

    # Cleanup
    rm -f /tmp/worker_build_output.log /tmp/worker_deploy_output.log 2>/dev/null

    print_success "🎉 Worker deployment completed successfully!"
}

# Run main function
main "$@"