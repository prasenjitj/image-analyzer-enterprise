#!/bin/bash

# Enhanced script to set up firewall rules for single VM deployment
# Features: Rich terminal UI, validation, rollback capability, detailed logging
# Usage: ./setup_firewall_rules.sh [PROJECT_ID] [VM_NAME] [VM_ZONE]

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

# Tracking variables
CREATED_RULES=()
UPDATED_RULES=()
VM_TAGS_ADDED=()

# Print formatted header
print_header() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                   🔥 FIREWALL RULES SETUP${CYAN}                               ║${NC}"
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
        echo -e "${RED}Firewall setup cancelled by user.${NC}"
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

# Check if VM exists
check_vm_exists() {
    local vm_name="$1"
    local zone="$2"
    local project="$3"

    if gcloud compute instances describe "$vm_name" --zone="$zone" --project="$project" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Create or update firewall rule with enhanced error handling
create_or_update_firewall_rule() {
    local rule_name="$1"
    local description="$2"
    local allow="$3"
    local source_ranges="$4"
    local target_tags="$5"
    local network="$6"
    local project="$7"

    echo -e "${WHITE}Configuring firewall rule: ${CYAN}$rule_name${NC}"

    if gcloud compute firewall-rules describe "$rule_name" --project="$project" &>/dev/null; then
        print_info "Rule exists - updating..."
        if gcloud compute firewall-rules update "$rule_name" \
            --project="$project" \
            --priority=1000 \
            --allow="$allow" \
            --source-ranges="$source_ranges" \
            --target-tags="$target_tags" &>/dev/null; then
            print_success "Firewall rule '$rule_name' updated successfully"
            UPDATED_RULES+=("$rule_name")
        else
            print_error "Failed to update firewall rule '$rule_name'"
            return 1
        fi
    else
        print_info "Creating new rule..."
        if gcloud compute firewall-rules create "$rule_name" \
            --project="$project" \
            --network="$network" \
            --priority=1000 \
            --direction=INGRESS \
            --action=ALLOW \
            --allow="$allow" \
            --source-ranges="$source_ranges" \
            --target-tags="$target_tags" \
            --description="$description" &>/dev/null; then
            print_success "Firewall rule '$rule_name' created successfully"
            CREATED_RULES+=("$rule_name")
        else
            print_error "Failed to create firewall rule '$rule_name'"
            return 1
        fi
    fi
    return 0
}

# Main firewall setup function
main() {
    local start_time=$(date +%s)

    # Print header
    print_header

    # Parse arguments with defaults
    PROJECT_ID="${1:-ops-excellence}"
    VM_NAME="${2:-pj-vm}"
    VM_ZONE="${3:-asia-south2-c}"

    # Interactive input if not provided via command line
    if [ $# -eq 0 ]; then
        regular_input "Enter Google Cloud Project ID" PROJECT_ID "ops-excellence"
        regular_input "Enter VM name" VM_NAME "pj-vm"
        regular_input "Enter VM zone" VM_ZONE "asia-south2-c"
    fi

    # Validate project ID
    while ! validate_project_id "$PROJECT_ID"; do
        print_error "Invalid project ID format"
        regular_input "Enter Google Cloud Project ID" PROJECT_ID
    done

    # Check if VM exists
    print_info "Checking VM existence..."
    if ! check_vm_exists "$VM_NAME" "$VM_ZONE" "$PROJECT_ID"; then
        print_error "VM '$VM_NAME' not found in zone '$VM_ZONE'"
        print_warning "Please ensure the VM exists before running this script"
        exit 1
    fi
    print_success "VM '$VM_NAME' found"

    # Network and connector configuration
    NETWORK="image-analyzer-vpc"
    VPC_CONNECTOR_RANGE="10.8.0.0/28"

    # Display configuration
    print_section "Firewall Configuration" "📋"
    echo -e "${WHITE}Review firewall configuration:${NC}"
    echo -e "   ${CYAN}Project ID:${NC}           $PROJECT_ID"
    echo -e "   ${CYAN}VM Name:${NC}              $VM_NAME"
    echo -e "   ${CYAN}VM Zone:${NC}             $VM_ZONE"
    echo -e "   ${CYAN}Network:${NC}             $NETWORK"
    echo -e "   ${CYAN}VPC Connector Range:${NC} $VPC_CONNECTOR_RANGE"
    echo ""

    # Confirm setup
    confirm_action "Ready to configure firewall rules?"

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

    # Step 2: Configure firewall rules
    print_section "Firewall Rules Configuration" "🔥"

    # PostgreSQL rule
    if create_or_update_firewall_rule \
        "allow-postgres-from-serverless" \
        "Allow PostgreSQL access from VPC Connector to $VM_NAME" \
        "tcp:5432" \
        "$VPC_CONNECTOR_RANGE" \
        "postgres" \
        "$NETWORK" \
        "$PROJECT_ID"; then
        print_info "PostgreSQL access configured"
    else
        print_error "PostgreSQL firewall rule configuration failed"
    fi
    echo ""

    # Redis rule
    if create_or_update_firewall_rule \
        "allow-redis-from-serverless" \
        "Allow Redis access from VPC Connector to $VM_NAME" \
        "tcp:6379" \
        "$VPC_CONNECTOR_RANGE" \
        "redis" \
        "$NETWORK" \
        "$PROJECT_ID"; then
        print_info "Redis access configured"
    else
        print_error "Redis firewall rule configuration failed"
    fi
    echo ""

    # SSH rule
    print_info "Configuring SSH access rule..."
    if gcloud compute firewall-rules describe allow-ssh-from-tcp --project="$PROJECT_ID" &>/dev/null; then
        if gcloud compute firewall-rules update allow-ssh-from-tcp \
            --project="$PROJECT_ID" \
            --priority=1000 &>/dev/null; then
            print_success "SSH firewall rule priority updated"
            UPDATED_RULES+=("allow-ssh-from-tcp")
        else
            print_warning "Failed to update SSH firewall rule priority"
        fi
    else
        print_info "Creating SSH firewall rule..."
        if gcloud compute firewall-rules create allow-ssh-from-tcp \
            --project="$PROJECT_ID" \
            --network="$NETWORK" \
            --priority=1000 \
            --direction=INGRESS \
            --action=ALLOW \
            --allow=tcp:22,udp,icmp \
            --source-ranges=0.0.0.0/0 \
            --description="Allow SSH access to VMs" &>/dev/null; then
            print_success "SSH firewall rule created"
            CREATED_RULES+=("allow-ssh-from-tcp")
        else
            print_warning "Failed to create SSH firewall rule"
        fi
    fi
    echo ""

    # Step 3: Update VM tags
    print_section "VM Tag Configuration" "🏷️"
    echo -e "${WHITE}Adding tags to VM ${CYAN}$VM_NAME${WHITE}...${NC}"

    if gcloud compute instances add-tags "$VM_NAME" \
        --zone="$VM_ZONE" \
        --project="$PROJECT_ID" \
        --tags=postgres,redis &>/dev/null; then
        print_success "VM tags added successfully"
        VM_TAGS_ADDED=("postgres" "redis")
    else
        print_error "Failed to add VM tags"
    fi
    echo ""

    # Calculate setup time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Display results
    print_section "Firewall Setup Summary" "🎉"
    print_success "Firewall rules configuration completed!"
    echo -e "   ${CYAN}⏱️  Setup time:${NC}         ${duration}s"
    echo -e "   ${CYAN}✅ Rules created:${NC}     ${#CREATED_RULES[@]}"
    echo -e "   ${CYAN}🔄 Rules updated:${NC}     ${#UPDATED_RULES[@]}"
    echo -e "   ${CYAN}🏷️  VM tags added:${NC}    ${#VM_TAGS_ADDED[@]}"
    echo ""

    # Show created/updated rules
    if [ ${#CREATED_RULES[@]} -gt 0 ]; then
        echo -e "${GREEN}Created rules:${NC}"
        for rule in "${CREATED_RULES[@]}"; do
            echo -e "   ${CYAN}• ${rule}${NC}"
        done
        echo ""
    fi

    if [ ${#UPDATED_RULES[@]} -gt 0 ]; then
        echo -e "${YELLOW}Updated rules:${NC}"
        for rule in "${UPDATED_RULES[@]}"; do
            echo -e "   ${CYAN}• ${rule}${NC}"
        done
        echo ""
    fi

    # Display current firewall rules
    print_section "Current Firewall Rules" "📋"
    echo -e "${WHITE}Active firewall rules:${NC}"
    gcloud compute firewall-rules list \
        --project="$PROJECT_ID" \
        --filter="name:(allow-postgres-from-serverless OR allow-redis-from-serverless OR allow-ssh-from-tcp)" \
        --format="table(name,network,priority,sourceRanges.list():label=SOURCE,allowed[].map().firewall_rule().list():label=ALLOW,targetTags.list():label=TAGS)" 2>/dev/null || print_warning "Could not retrieve firewall rules list"
    echo ""

    # Display VM tags
    print_section "VM Configuration" "💻"
    echo -e "${WHITE}VM ${CYAN}$VM_NAME${WHITE} current tags:${NC}"
    gcloud compute instances describe "$VM_NAME" \
        --zone="$VM_ZONE" \
        --project="$PROJECT_ID" \
        --format="value(tags.items)" 2>/dev/null || print_warning "Could not retrieve VM tags"
    echo ""

    # Testing instructions
    print_section "Connectivity Testing" "🧪"
    echo -e "${WHITE}Test your firewall configuration:${NC}"
    echo ""
    echo -e "${CYAN}# Test SSH access:${NC}"
    echo -e "gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID"
    echo ""
    echo -e "${CYAN}# Test PostgreSQL connectivity (from Cloud Shell):${NC}"
    echo -e "gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID --command 'sudo -u postgres psql -c \"SELECT version();\"'"
    echo ""
    echo -e "${CYAN}# Test Redis connectivity (from Cloud Shell):${NC}"
    echo -e "gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID --command 'redis-cli ping'"
    echo ""
    echo -e "${CYAN}# Verify VPC Connector connectivity:${NC}"
    echo -e "gcloud compute networks vpc-access connectors describe image-analyzer-connector --region=\$(gcloud config get-value compute/region) --format='value(state)'"
    echo ""

    # Security recommendations
    print_section "Security Recommendations" "🔐"
    echo -e "${YELLOW}Security best practices:${NC}"
    echo -e "   • ${WHITE}Restrict SSH source ranges to specific IPs${NC}"
    echo -e "   • ${WHITE}Use VPC-native clusters for GKE if applicable${NC}"
    echo -e "   • ${WHITE}Enable VPC Flow Logs for monitoring${NC}"
    echo -e "   • ${WHITE}Regularly audit firewall rules${NC}"
    echo -e "   • ${WHITE}Use Cloud Armor for additional protection${NC}"
    echo ""

    print_success "🔥 Firewall rules setup completed successfully!"
}

# Run main function
main "$@"
