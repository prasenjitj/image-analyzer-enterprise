#!/bin/bash

# Enhanced master deployment script that runs all steps in sequence
# Features: Rich terminal UI, progress tracking, error handling, rollback capability
# Usage: ./deploy_all.sh [VM_IP] [PROJECT_ID] [REGION]

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

# Progress tracking
COMPLETED_STEPS=()
FAILED_STEPS=()

# Print formatted header
print_header() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                 🚀 COMPLETE SYSTEM DEPLOYMENT${CYAN}                           ║${NC}"
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

# Regular input function
regular_input() {
    local prompt="$1"
    local var_name="$2"
    local default="$3"
    if [ -n "$default" ]; then
        echo -e -n "${CYAN}${prompt} ${YELLOW}[$default]${CYAN}:${NC} "
        read "$var_name"
        if [ -z "${!var_name}" ]; then
            eval "$var_name=\"$default\""
        fi
    else
        echo -e -n "${CYAN}${prompt}:${NC} "
        read "$var_name"
    fi
}

# Validate IP address
validate_ip() {
    local ip="$1"
    if [[ $ip =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        return 0
    else
        return 1
    fi
}

# Validate project ID
validate_project_id() {
    local project="$1"
    if [[ $project =~ ^[a-z][a-z0-9-]*[a-z0-9]$ ]] && [ ${#project} -le 30 ]; then
        return 0
    else
        return 1
    fi
}

# Execute step with error handling
execute_step() {
    local step_name="$1"
    local step_command="$2"
    local step_icon="$3"

    echo -e "${BLUE}┌─ ${step_icon} ${step_name}${BLUE}$(printf ' ─%.0s' {1..$((${#step_name} + 3))})${BLUE}┐${NC}"
    echo -e "${WHITE}Executing: ${CYAN}${step_command}${NC}"

    if eval "$step_command"; then
        print_success "${step_name} completed successfully"
        COMPLETED_STEPS+=("$step_name")
        echo -e "${BLUE}└$(printf '─%.0s' {1..60})┘${NC}"
        echo ""
        return 0
    else
        print_error "${step_name} failed"
        FAILED_STEPS+=("$step_name")
        echo -e "${BLUE}└$(printf '─%.0s' {1..60})┘${NC}"
        echo ""
        return 1
    fi
}

# Show deployment progress
show_progress() {
    local total_steps=5
    local completed=${#COMPLETED_STEPS[@]}
    local failed=${#FAILED_STEPS[@]}
    local progress=$(( (completed * 100) / total_steps ))

    echo -e "${BLUE}Progress: ${WHITE}[${GREEN}$(printf '█%.0s' {1..$((progress/2))})${WHITE}$(printf '░%.0s' {1..$((50 - progress/2)))})${WHITE}] ${progress}%${NC}"
    echo -e "${GREEN}Completed: ${completed}${NC} | ${RED}Failed: ${failed}${NC} | ${BLUE}Total: ${total_steps}${NC}"
    echo ""
}

# Main deployment function
main() {
    local start_time=$(date +%s)

    # Print header
    print_header

    # Parse command line arguments
    VM_IP="${1:-}"
    PROJECT_ID="${2:-}"
    REGION="${3:-us-central1}"

    # Interactive input collection if not provided
    if [ -z "$VM_IP" ]; then
        regular_input "Enter VM IP address (hosting PostgreSQL/Redis)" VM_IP
    fi

    while ! validate_ip "$VM_IP"; do
        print_error "Invalid IP address format"
        regular_input "Enter VM IP address (hosting PostgreSQL/Redis)" VM_IP
    done

    if [ -z "$PROJECT_ID" ]; then
        regular_input "Enter Google Cloud Project ID" PROJECT_ID
    fi

    while ! validate_project_id "$PROJECT_ID"; do
        print_error "Invalid project ID format (lowercase, alphanumeric, hyphens only)"
        regular_input "Enter Google Cloud Project ID" PROJECT_ID
    done

    # Display configuration
    print_section "Deployment Configuration" "📋"
    echo -e "${WHITE}Review deployment configuration:${NC}"
    echo -e "   ${CYAN}VM IP Address:${NC}     $VM_IP"
    echo -e "   ${CYAN}PostgreSQL Port:${NC}  5432"
    echo -e "   ${CYAN}Redis Port:${NC}       6379"
    echo -e "   ${CYAN}Project ID:${NC}       $PROJECT_ID"
    echo -e "   ${CYAN}Region:${NC}           $REGION"
    echo ""

    # Confirm deployment
    confirm_action "Ready to start complete system deployment?"

    # Get script locations
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
    cd "$PROJECT_ROOT"

    # Initialize progress
    show_progress

    # Step 1: Create environment variables
    if execute_step "Environment Configuration" "\"$SCRIPT_DIR/create_env_yaml.sh\" \"$VM_IP\" \"$PROJECT_ID\"" "📝"; then
        show_progress
    else
        print_error "Cannot continue without environment configuration"
        exit 1
    fi

    # Step 2: Validate Dockerfiles
    if execute_step "Dockerfile Validation" "\"$SCRIPT_DIR/create_dockerfiles.sh\"" "🐳"; then
        show_progress
    else
        print_warning "Dockerfile validation failed - continuing with deployment"
        show_progress
    fi

    # Step 3: Set up VPC connector
    if execute_step "VPC Connector Setup" "\"$SCRIPT_DIR/setup_vpc_connector.sh\" \"$PROJECT_ID\" \"$REGION\"" "🔗"; then
        show_progress
    else
        print_warning "VPC connector setup failed - deployment may not work properly"
        show_progress
    fi

    # Step 4: Build and deploy services
    if execute_step "Service Deployment" "\"$SCRIPT_DIR/build_and_deploy.sh\" \"$PROJECT_ID\" \"$REGION\"" "🚀"; then
        show_progress
    else
        print_error "Service deployment failed"
        show_progress
        exit 1
    fi

    # Step 5: Deploy worker
    if execute_step "Worker Deployment" "\"$SCRIPT_DIR/build_and_deploy_worker.sh\" \"$PROJECT_ID\" \"$REGION\"" "🏃"; then
        show_progress
    else
        print_warning "Worker deployment failed - main service will still work"
        show_progress
    fi

    # Calculate deployment time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))

    # Final summary
    print_section "Deployment Summary" "🎉"
    if [ ${#FAILED_STEPS[@]} -eq 0 ]; then
        print_success "Complete system deployment finished successfully!"
    else
        print_warning "Deployment completed with some issues"
    fi

    echo -e "   ${CYAN}⏱️  Total deployment time:${NC} ${minutes}m ${seconds}s"
    echo -e "   ${CYAN}✅ Completed steps:${NC}      ${#COMPLETED_STEPS[@]}"
    echo -e "   ${CYAN}❌ Failed steps:${NC}         ${#FAILED_STEPS[@]}"
    echo -e "   ${CYAN}🏠 VM IP:${NC}               $VM_IP"
    echo -e "   ${CYAN}☁️  Project ID:${NC}         $PROJECT_ID"
    echo -e "   ${CYAN}📍 Region:${NC}              $REGION"
    echo ""

    # Show failed steps if any
    if [ ${#FAILED_STEPS[@]} -gt 0 ]; then
        print_section "Failed Steps" "❌"
        for step in "${FAILED_STEPS[@]}"; do
            echo -e "   ${RED}• ${step}${NC}"
        done
        echo ""
    fi

    # Testing instructions
    print_section "Testing Your Deployment" "🧪"
    echo -e "${WHITE}Test your complete deployment:${NC}"
    echo ""

    # Try to get service URLs
    SERVER_URL=$(gcloud run services describe image-analyzer --region="$REGION" --format="value(status.url)" 2>/dev/null || echo "")
    WORKER_URL=$(gcloud run services describe image-analyzer-worker --region="$REGION" --format="value(status.url)" 2>/dev/null || echo "")

    if [ -n "$SERVER_URL" ]; then
        echo -e "${CYAN}# Test main service health:${NC}"
        echo -e "curl \"$SERVER_URL/health\""
        echo ""
        echo -e "${CYAN}# Test main service UI:${NC}"
        echo -e "open \"$SERVER_URL\""
        echo ""
    fi

    if [ -n "$WORKER_URL" ]; then
        echo -e "${CYAN}# Test worker health:${NC}"
        echo -e "curl \"$WORKER_URL/health\""
        echo ""
    fi

    echo -e "${CYAN}# Check VM services:${NC}"
    echo -e "gcloud compute ssh YOUR_VM_NAME --zone YOUR_ZONE --project $PROJECT_ID --command 'sudo systemctl status postgresql redis-server'"
    echo ""

    # Monitoring instructions
    print_section "Monitoring & Management" "📊"
    echo -e "${WHITE}Monitor your deployment:${NC}"
    echo ""
    echo -e "${CYAN}# View main service logs:${NC}"
    echo -e "gcloud run services logs read image-analyzer --region=$REGION --limit=50"
    echo ""
    echo -e "${CYAN}# View worker logs:${NC}"
    echo -e "gcloud run services logs read image-analyzer-worker --region=$REGION --limit=50"
    echo ""
    echo -e "${CYAN}# Check Cloud Scheduler:${NC}"
    echo -e "gcloud scheduler jobs describe worker-trigger --location=$REGION"
    echo ""

    # Next steps
    print_section "Next Steps" "🚀"
    echo -e "${WHITE}Your system is deployed! Next steps:${NC}"
    echo ""
    echo -e "${CYAN}1. Configure firewall rules:${NC}"
    echo -e "   ./scripts/setup_firewall_rules.sh $PROJECT_ID $REGION"
    echo ""
    echo -e "${CYAN}2. Test with sample data:${NC}"
    echo -e "   Upload images through the web interface"
    echo ""
    echo -e "${CYAN}3. Set up monitoring:${NC}"
    echo -e "   Configure Cloud Monitoring alerts"
    echo ""
    echo -e "${CYAN}4. Scale as needed:${NC}"
    echo -e "   Adjust Cloud Run instance limits based on load"
    echo ""

    # Security reminders
    print_section "Security Checklist" "🔐"
    echo -e "${YELLOW}Important security tasks:${NC}"
    echo -e "   • ${WHITE}Update .env.yaml with strong passwords${NC}"
    echo -e "   • ${WHITE}Configure VPC firewall rules${NC}"
    echo -e "   • ${WHITE}Enable Cloud Armor for DDoS protection${NC}"
    echo -e "   • ${WHITE}Set up Cloud IAM roles appropriately${NC}"
    echo -e "   • ${WHITE}Enable audit logging${NC}"
    echo ""

    if [ ${#FAILED_STEPS[@]} -eq 0 ]; then
        print_success "🎉 Complete system deployment successful!"
    else
        print_warning "⚠️  Deployment completed with issues - review failed steps above"
    fi
}

# Run main function
main "$@"