#!/bin/bash

# Enhanced script to set up VPC connector for Cloud Functions/Cloud Run
# Features: Rich terminal UI, validation, detailed status reporting, network checks
# Usage: ./setup_vpc_connector.sh [PROJECT_ID] [REGION] [NETWORK] [CONNECTOR_NAME] [RANGE]

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
    echo -e "${CYAN}║${WHITE}                   🔗 VPC CONNECTOR SETUP${CYAN}                               ║${NC}"
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
        echo -e "${RED}VPC connector setup cancelled by user.${NC}"
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

# Validate project ID
validate_project_id() {
    local project="$1"
    if [[ $project =~ ^[a-z][a-z0-9-]*[a-z0-9]$ ]] && [ ${#project} -le 30 ]; then
        return 0
    else
        return 1
    fi
}

# Validate CIDR range
validate_cidr() {
    local cidr="$1"
    if [[ $cidr =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
        return 0
    else
        return 1
    fi
}

# Check if network exists
check_network_exists() {
    local network="$1"
    local project="$2"

    if gcloud compute networks describe "$network" --project="$project" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Check VPC connector status
check_connector_status() {
    local connector="$1"
    local region="$2"
    local project="$3"

    local status
    status=$(gcloud compute networks vpc-access connectors describe "$connector" \
        --region="$region" \
        --project="$project" \
        --format="value(state)" 2>/dev/null)

    echo "$status"
}

# Main VPC connector setup function
main() {
    local start_time=$(date +%s)

    # Print header
    print_header

    # Parse arguments with defaults
    PROJECT_ID="${1:-ops-excellence}"
    REGION="${2:-asia-south2}"
    NETWORK="${3:-image-analyzer-vpc}"
    CONNECTOR_NAME="${4:-image-analyzer-connector}"
    RANGE="${5:-10.8.0.0/28}"

    # Interactive input if not provided via command line
    if [ $# -eq 0 ]; then
        regular_input "Enter Google Cloud Project ID" PROJECT_ID "ops-excellence"
        regular_input "Enter GCP Region" REGION "asia-south2"
        regular_input "Enter VPC Network name" NETWORK "image-analyzer-vpc"
        regular_input "Enter VPC Connector name" CONNECTOR_NAME "image-analyzer-connector"
        regular_input "Enter IP range (CIDR)" RANGE "10.8.0.0/28"
    fi

    # Validate inputs
    while ! validate_project_id "$PROJECT_ID"; do
        print_error "Invalid project ID format"
        regular_input "Enter Google Cloud Project ID" PROJECT_ID
    done

    while ! validate_cidr "$RANGE"; do
        print_error "Invalid CIDR range format (e.g., 10.8.0.0/28)"
        regular_input "Enter IP range (CIDR)" RANGE
    done

    # Check if network exists
    print_info "Checking VPC network existence..."
    if ! check_network_exists "$NETWORK" "$PROJECT_ID"; then
        print_error "VPC network '$NETWORK' not found in project '$PROJECT_ID'"
        print_warning "Please create the VPC network first or check the network name"
        print_info "To create a VPC network:"
        echo -e "${CYAN}gcloud compute networks create $NETWORK --project=$PROJECT_ID${NC}"
        exit 1
    fi
    print_success "VPC network '$NETWORK' found"

    # Display configuration
    print_section "VPC Connector Configuration" "📋"
    echo -e "${WHITE}Review VPC connector configuration:${NC}"
    echo -e "   ${CYAN}Project ID:${NC}       $PROJECT_ID"
    echo -e "   ${CYAN}Region:${NC}           $REGION"
    echo -e "   ${CYAN}VPC Network:${NC}      $NETWORK"
    echo -e "   ${CYAN}Connector Name:${NC}    $CONNECTOR_NAME"
    echo -e "   ${CYAN}IP Range:${NC}         $RANGE"
    echo ""

    # Confirm setup
    confirm_action "Ready to set up VPC connector?"

    # Step 1: Set GCP project
    print_section "Project Setup" "📋"
    echo -e "${WHITE}Setting GCP project to ${CYAN}$PROJECT_ID${WHITE}...${NC}"
    if gcloud config set project "$PROJECT_ID" > /dev/null 2>&1; then
        print_success "GCP project set successfully"
    else
        print_error "Failed to set GCP project"
        exit 1
    fi
    echo ""

    # Step 2: Check existing connector
    print_section "VPC Connector Status" "🔍"
    echo -e "${WHITE}Checking existing VPC connector...${NC}"

    local existing_status
    existing_status=$(check_connector_status "$CONNECTOR_NAME" "$REGION" "$PROJECT_ID")

    if [ -n "$existing_status" ]; then
        print_info "VPC connector '$CONNECTOR_NAME' already exists"
        echo -e "   ${CYAN}Status:${NC} $existing_status"

        if [ "$existing_status" = "READY" ]; then
            print_success "VPC connector is ready for use"
        elif [ "$existing_status" = "CREATING" ]; then
            print_warning "VPC connector is still being created - please wait"
            print_info "You can check status later with:"
            echo -e "${CYAN}gcloud compute networks vpc-access connectors describe $CONNECTOR_NAME --region=$REGION${NC}"
            exit 0
        else
            print_warning "VPC connector status: $existing_status"
            print_info "You may need to delete and recreate the connector"
        fi
    else
        print_info "VPC connector does not exist - will create new one"
    fi
    echo ""

    # Step 3: Create VPC connector if needed
    if [ -z "$existing_status" ]; then
        print_section "Creating VPC Connector" "🏗️"
        echo -e "${WHITE}Creating VPC connector ${CYAN}$CONNECTOR_NAME${WHITE}...${NC}"
        echo -e "${YELLOW}This may take 2-3 minutes...${NC}"

        if gcloud compute networks vpc-access connectors create "$CONNECTOR_NAME" \
            --network="$NETWORK" \
            --region="$REGION" \
            --range="$RANGE" \
            --project="$PROJECT_ID" > /tmp/connector_creation.log 2>&1; then

            print_success "VPC connector creation initiated"

            # Wait for connector to be ready
            echo -e "${WHITE}Waiting for connector to be ready...${NC}"
            local attempts=0
            local max_attempts=30

            while [ $attempts -lt $max_attempts ]; do
                local status
                status=$(check_connector_status "$CONNECTOR_NAME" "$REGION" "$PROJECT_ID")

                if [ "$status" = "READY" ]; then
                    print_success "VPC connector is now ready!"
                    break
                elif [ "$status" = "CREATING" ]; then
                    echo -n "."
                    sleep 10
                    ((attempts++))
                else
                    print_error "VPC connector creation failed with status: $status"
                    echo -e "${RED}Creation log:${NC}"
                    cat /tmp/connector_creation.log
                    exit 1
                fi
            done

            if [ $attempts -eq $max_attempts ]; then
                print_warning "VPC connector creation timed out"
                print_info "Check status manually:"
                echo -e "${CYAN}gcloud compute networks vpc-access connectors describe $CONNECTOR_NAME --region=$REGION${NC}"
            fi

        else
            print_error "Failed to create VPC connector"
            echo -e "${RED}Error details:${NC}"
            cat /tmp/connector_creation.log
            exit 1
        fi

        # Clean up temp file
        rm -f /tmp/connector_creation.log
        echo ""
    fi

    # Step 4: Get final connector details
    print_section "VPC Connector Details" "📡"
    echo -e "${WHITE}VPC connector information:${NC}"

    gcloud compute networks vpc-access connectors describe "$CONNECTOR_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format="table(name,network,ipCidrRange,state,machineType,minInstances,maxInstances)" 2>/dev/null || print_warning "Could not retrieve connector details"
    echo ""

    # Calculate setup time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Final summary
    print_section "VPC Connector Setup Summary" "🎉"
    local final_status
    final_status=$(check_connector_status "$CONNECTOR_NAME" "$REGION" "$PROJECT_ID")

    if [ "$final_status" = "READY" ]; then
        print_success "VPC connector setup completed successfully!"
        echo -e "   ${CYAN}⏱️  Setup time:${NC}     ${duration}s"
        echo -e "   ${CYAN}🔗 Connector:${NC}     $CONNECTOR_NAME"
        echo -e "   ${CYAN}📍 Region:${NC}        $REGION"
        echo -e "   ${CYAN}🌐 Network:${NC}       $NETWORK"
        echo -e "   ${CYAN}📋 IP Range:${NC}      $RANGE"
        echo -e "   ${CYAN}✅ Status:${NC}        $final_status"
    else
        print_warning "VPC connector setup completed with status: $final_status"
        echo -e "   ${CYAN}⏱️  Setup time:${NC}     ${duration}s"
    fi
    echo ""

    # Usage instructions
    print_section "Usage Instructions" "📚"
    echo -e "${WHITE}How to use the VPC connector:${NC}"
    echo ""
    echo -e "${CYAN}# Cloud Run service with VPC connector:${NC}"
    echo -e "gcloud run deploy my-service --vpc-connector=$CONNECTOR_NAME --region=$REGION"
    echo ""
    echo -e "${CYAN}# Cloud Functions with VPC connector:${NC}"
    echo -e "gcloud functions deploy my-function --vpc-connector=$CONNECTOR_NAME --region=$REGION"
    echo ""
    echo -e "${CYAN}# Check connector status:${NC}"
    echo -e "gcloud compute networks vpc-access connectors describe $CONNECTOR_NAME --region=$REGION"
    echo ""
    echo -e "${CYAN}# List all connectors:${NC}"
    echo -e "gcloud compute networks vpc-access connectors list --region=$REGION"
    echo ""

    # Troubleshooting
    print_section "Troubleshooting" "🔧"
    echo -e "${WHITE}Common issues and solutions:${NC}"
    echo ""
    echo -e "${YELLOW}• Connector stuck in CREATING state:${NC}"
    echo -e "   Wait a few more minutes or delete and recreate"
    echo ""
    echo -e "${YELLOW}• IP range conflicts:${NC}"
    echo -e "   Choose a different CIDR range that doesn't overlap with existing subnets"
    echo ""
    echo -e "${YELLOW}• Network not found:${NC}"
    echo -e "   Ensure the VPC network exists in the specified project"
    echo ""
    echo -e "${YELLOW}• Permission denied:${NC}"
    echo -e "   Ensure you have vpcaccess.connectors.create permission"
    echo ""

    if [ "$final_status" = "READY" ]; then
        print_success "🔗 VPC connector is ready for use!"
    else
        print_warning "⚠️  Please check connector status before using"
    fi
}

# Run main function
main "$@"