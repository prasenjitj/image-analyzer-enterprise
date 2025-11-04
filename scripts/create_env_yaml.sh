#!/bin/bash

# Enhanced script to create/update .env.yaml file with proper configuration
# Features: Interactive prompts, rich terminal UI, validation, secure input handling
# Usage: ./create_env_yaml.sh [VM_IP] [PROJECT_ID]

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
    echo -e "${CYAN}║${WHITE}                 🔧 ENVIRONMENT CONFIGURATION TOOL${CYAN}                        ║${NC}"
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

# Secure input function (hides password input)
secure_input() {
    local prompt="$1"
    local var_name="$2"
    echo -e -n "${CYAN}${prompt}:${NC} "
    read -s "$var_name"
    echo ""
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

# Generate secure random key
generate_secret_key() {
    openssl rand -hex 32
}

# Main configuration function
main() {
    local start_time=$(date +%s)

    # Print header
    print_header

    # Parse command line arguments
    VM_IP="${1:-}"
    PROJECT_ID="${2:-}"

    # Interactive input collection
    print_section "Configuration Input" "📝"

    # VM IP Address
    if [ -z "$VM_IP" ]; then
        regular_input "Enter VM IP address" VM_IP
    fi

    while ! validate_ip "$VM_IP"; do
        print_error "Invalid IP address format"
        regular_input "Enter VM IP address" VM_IP
    done

    print_success "VM IP: $VM_IP"

    # Project ID
    if [ -z "$PROJECT_ID" ]; then
        regular_input "Enter Google Cloud Project ID" PROJECT_ID
    fi

    while ! validate_project_id "$PROJECT_ID"; do
        print_error "Invalid project ID format (lowercase, alphanumeric, hyphens only)"
        regular_input "Enter Google Cloud Project ID" PROJECT_ID
    done

    print_success "Project ID: $PROJECT_ID"
    echo ""

    # Database configuration
    print_section "Database Configuration" "🗄️"
    regular_input "Database username" DB_USER "postgres"
    secure_input "Database password" DB_PASSWORD
    print_success "Database credentials configured"
    echo ""

    # Redis configuration
    print_section "Redis Configuration" "🔴"
    regular_input "Redis password (leave empty if no password)" REDIS_PASSWORD
    if [ -z "$REDIS_PASSWORD" ]; then
        print_info "Redis configured without password"
    else
        print_success "Redis password configured"
    fi
    echo ""

    # API Keys
    print_section "API Keys & Secrets" "🔑"
    secure_input "Google Vision API Key" GOOGLE_API_KEY
    print_success "Google API key configured"

    # Generate or input secret key
    echo ""
    echo -e "${YELLOW}Flask Secret Key:${NC}"
    echo -e "   ${CYAN}1) Generate secure random key${NC}"
    echo -e "   ${CYAN}2) Enter custom key${NC}"
    echo -e -n "${CYAN}Choose option (1/2) ${YELLOW}[1]${CYAN}:${NC} "
    read -n 1 SECRET_CHOICE
    echo ""

    if [ "$SECRET_CHOICE" = "2" ]; then
        secure_input "Enter Flask secret key" SECRET_KEY
    else
        SECRET_KEY=$(generate_secret_key)
        print_success "Generated secure random secret key"
    fi
    echo ""

    # Cloud Storage buckets
    print_section "Cloud Storage Configuration" "☁️"
    regular_input "Upload bucket name" UPLOAD_BUCKET "${PROJECT_ID}-uploads"
    regular_input "Export bucket name" EXPORT_BUCKET "${PROJECT_ID}-exports"
    print_success "Cloud Storage buckets configured"
    echo ""

    # Application settings
    print_section "Application Settings" "⚙️"
    regular_input "Max upload size (bytes)" MAX_UPLOAD_SIZE "104857600"
    regular_input "Chunk size for processing" CHUNK_SIZE "1000"
    regular_input "Max concurrent batches" MAX_CONCURRENT_BATCHES "10"
    regular_input "Requests per minute limit" REQUESTS_PER_MINUTE "55"
    print_success "Application settings configured"
    echo ""

    # Create .env.yaml file
    print_section "Creating Configuration File" "📄"
    echo -e "${WHITE}Creating .env.yaml configuration file...${NC}"

    cat > .env.yaml << EOF
# Image Analyzer Enterprise Environment Configuration
# Generated on $(date)
# Project: $PROJECT_ID
# VM IP: $VM_IP

# Database Configuration
DATABASE_URL: "postgresql://$DB_USER:$DB_PASSWORD@$VM_IP:5432/imageprocessing"

# Redis Configuration
REDIS_URL: "redis://:$REDIS_PASSWORD@$VM_IP:6379/0"

# API Keys
GOOGLE_API_KEY: "$GOOGLE_API_KEY"
SECRET_KEY: "$SECRET_KEY"

# Cloud Storage
UPLOAD_BUCKET: "gs://$UPLOAD_BUCKET"
EXPORT_BUCKET: "gs://$EXPORT_BUCKET"

# Application Limits
MAX_UPLOAD_SIZE: "$MAX_UPLOAD_SIZE"
CHUNK_SIZE: "$CHUNK_SIZE"
MAX_CONCURRENT_BATCHES: "$MAX_CONCURRENT_BATCHES"
REQUESTS_PER_MINUTE: "$REQUESTS_PER_MINUTE"
EOF

    print_success ".env.yaml created successfully"
    echo ""

    # Security check
    print_section "Security Validation" "🔒"
    echo -e "${WHITE}Performing security validation...${NC}"

    if [ ${#SECRET_KEY} -lt 32 ]; then
        print_warning "Secret key is shorter than recommended (32+ characters)"
    else
        print_success "Secret key length is adequate"
    fi

    if [ ${#GOOGLE_API_KEY} -lt 20 ]; then
        print_warning "Google API key seems short - please verify"
    else
        print_success "Google API key format appears valid"
    fi

    if [ -z "$DB_PASSWORD" ]; then
        print_warning "Database password is empty"
    else
        print_success "Database password is set"
    fi
    echo ""

    # Calculate configuration time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Final summary
    print_section "Configuration Summary" "🎉"
    print_success "Environment configuration completed successfully!"
    echo -e "   ${CYAN}⏱️  Configuration time:${NC} ${duration}s"
    echo -e "   ${CYAN}📄 Config file:${NC}        .env.yaml"
    echo -e "   ${CYAN}🏠 VM IP:${NC}              $VM_IP"
    echo -e "   ${CYAN}☁️  Project ID:${NC}        $PROJECT_ID"
    echo -e "   ${CYAN}🗄️  Database:${NC}          PostgreSQL"
    echo -e "   ${CYAN}🔴 Redis:${NC}              Configured"
    echo -e "   ${CYAN}🔑 API Keys:${NC}          Set"
    echo ""

    # Next steps
    print_section "Next Steps" "🚀"
    echo -e "${WHITE}Your environment is configured! Next steps:${NC}"
    echo ""
    echo -e "${CYAN}# 1. Validate Dockerfiles:${NC}"
    echo -e "./scripts/create_dockerfiles.sh"
    echo ""
    echo -e "${CYAN}# 2. Deploy to Google Cloud:${NC}"
    echo -e "./scripts/build_and_deploy.sh"
    echo ""
    echo -e "${CYAN}# 3. Test the deployment:${NC}"
    echo -e "curl https://YOUR_SERVICE_URL/health"
    echo ""

    # Security reminder
    print_section "Security Reminder" "🔐"
    echo -e "${YELLOW}Important security notes:${NC}"
    echo -e "   • Keep .env.yaml secure and never commit to version control"
    echo -e "   • Rotate API keys regularly"
    echo -e "   • Use strong, unique passwords"
    echo -e "   • Monitor service access logs"
    echo ""

    print_success "🔧 Environment configuration completed successfully!"
}

# Run main function
main "$@"