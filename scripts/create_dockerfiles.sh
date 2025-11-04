#!/bin/bash

# Enhanced script to validate and ensure Dockerfiles are properly configured
# Features: Rich terminal UI, detailed validation, helpful error messages
# Usage: ./create_dockerfiles.sh

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
    echo -e "${CYAN}║${WHITE}                    🐳 DOCKERFILE VALIDATION TOOL${CYAN}                          ║${NC}"
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

# Validate Dockerfile content
validate_dockerfile() {
    local file="$1"
    local type="$2"

    print_info "Validating $type Dockerfile..."

    # Check if file exists
    if [ ! -f "$file" ]; then
        print_error "$type Dockerfile not found at $file"
        return 1
    fi

    print_success "$type Dockerfile exists"

    # Check for Python base image
    if ! grep -q "FROM python" "$file"; then
        print_error "$type Dockerfile doesn't appear to be Python-based"
        print_warning "Expected: FROM python:3.x"
        return 1
    fi

    print_success "$type Dockerfile uses Python base image"

    # Check for requirements.txt copy
    if ! grep -q "requirements.txt" "$file"; then
        print_warning "$type Dockerfile doesn't copy requirements.txt"
        print_info "Consider adding: COPY requirements.txt ."
    else
        print_success "$type Dockerfile includes requirements.txt"
    fi

    # Check for proper working directory
    if ! grep -q "WORKDIR" "$file"; then
        print_warning "$type Dockerfile doesn't set a working directory"
        print_info "Consider adding: WORKDIR /app"
    else
        print_success "$type Dockerfile sets working directory"
    fi

    # Check for CMD or ENTRYPOINT
    if ! grep -q "CMD\|ENTRYPOINT" "$file"; then
        print_error "$type Dockerfile missing CMD or ENTRYPOINT"
        return 1
    fi

    print_success "$type Dockerfile has execution command"

    return 0
}

# Main validation function
main() {
    local start_time=$(date +%s)

    # Print header
    print_header

    # Change to project root
    cd "$(dirname "$0")/.." # Go to project root

    # Step 1: Check project structure
    print_section "Project Structure Check" "📁"
    echo -e "${WHITE}Checking project structure...${NC}"

    if [ -f "requirements.txt" ]; then
        print_success "requirements.txt found"
    else
        print_warning "requirements.txt not found in project root"
    fi

    if [ -f "main.py" ]; then
        print_success "main.py found (entry point)"
    else
        print_warning "main.py not found (expected entry point)"
    fi

    if [ -d "src" ]; then
        print_success "src/ directory found"
    else
        print_warning "src/ directory not found"
    fi
    echo ""

    # Step 2: Validate main Dockerfile
    print_section "Main Dockerfile Validation" "🐳"
    if validate_dockerfile "Dockerfile" "Main"; then
        print_success "Main Dockerfile validation passed"
    else
        print_error "Main Dockerfile validation failed"
        echo ""
        print_section "Dockerfile Creation Help" "💡"
        echo -e "${WHITE}To create a basic Dockerfile, you can use:${NC}"
        echo ""
        echo -e "${CYAN}FROM python:3.11-slim${NC}"
        echo -e "${CYAN}WORKDIR /app${NC}"
        echo -e "${CYAN}COPY requirements.txt .${NC}"
        echo -e "${CYAN}RUN pip install --no-cache-dir -r requirements.txt${NC}"
        echo -e "${CYAN}COPY . .${NC}"
        echo -e "${CYAN}EXPOSE 8080${NC}"
        echo -e "${CYAN}CMD [\"python\", \"main.py\"]${NC}"
        echo ""
        exit 1
    fi
    echo ""

    # Step 3: Validate worker Dockerfile
    print_section "Worker Dockerfile Validation" "🏃"
    if validate_dockerfile "Dockerfile.worker" "Worker"; then
        print_success "Worker Dockerfile validation passed"
    else
        print_error "Worker Dockerfile validation failed"
        echo ""
        print_section "Worker Dockerfile Creation Help" "💡"
        echo -e "${WHITE}To create a basic worker Dockerfile, you can use:${NC}"
        echo ""
        echo -e "${CYAN}FROM python:3.11-slim${NC}"
        echo -e "${CYAN}WORKDIR /app${NC}"
        echo -e "${CYAN}COPY requirements.txt .${NC}"
        echo -e "${CYAN}RUN pip install --no-cache-dir -r requirements.txt${NC}"
        echo -e "${CYAN}COPY . .${NC}"
        echo -e "${CYAN}EXPOSE 8081${NC}"
        echo -e "${CYAN}CMD [\"python\", \"-m\", \"src.background_worker\"]${NC}"
        echo ""
        exit 1
    fi
    echo ""

    # Step 4: Cross-validation
    print_section "Cross-Validation" "🔍"
    echo -e "${WHITE}Checking for consistency between Dockerfiles...${NC}"

    # Check if both use same Python version
    MAIN_PYTHON_VERSION=$(grep "FROM python" Dockerfile | head -1 | sed 's/FROM python://' | sed 's/-.*//')
    WORKER_PYTHON_VERSION=$(grep "FROM python" Dockerfile.worker | head -1 | sed 's/FROM python://' | sed 's/-.*//')

    if [ "$MAIN_PYTHON_VERSION" = "$WORKER_PYTHON_VERSION" ]; then
        print_success "Both Dockerfiles use Python $MAIN_PYTHON_VERSION"
    else
        print_warning "Python version mismatch: Main=$MAIN_PYTHON_VERSION, Worker=$WORKER_PYTHON_VERSION"
    fi

    # Check if both expose different ports
    MAIN_PORT=$(grep "EXPOSE" Dockerfile | head -1 | awk '{print $2}')
    WORKER_PORT=$(grep "EXPOSE" Dockerfile.worker | head -1 | awk '{print $2}')

    if [ "$MAIN_PORT" != "$WORKER_PORT" ]; then
        print_success "Services use different ports: Main=$MAIN_PORT, Worker=$WORKER_PORT"
    else
        print_warning "Services may conflict on port $MAIN_PORT"
    fi
    echo ""

    # Calculate validation time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Final summary
    print_section "Validation Summary" "🎉"
    print_success "Dockerfile validation completed successfully!"
    echo -e "   ${CYAN}⏱️  Validation time:${NC} ${duration}s"
    echo -e "   ${CYAN}📄 Main Dockerfile:${NC}    Valid"
    echo -e "   ${CYAN}🏃 Worker Dockerfile:${NC}  Valid"
    echo ""

    # Next steps
    print_section "Next Steps" "🚀"
    echo -e "${WHITE}Your Dockerfiles are ready for deployment:${NC}"
    echo ""
    echo -e "${CYAN}# Build main service:${NC}"
    echo -e "docker build -f Dockerfile -t image-analyzer:latest ."
    echo ""
    echo -e "${CYAN}# Build worker service:${NC}"
    echo -e "docker build -f Dockerfile.worker -t image-analyzer-worker:latest ."
    echo ""
    echo -e "${CYAN}# Test locally:${NC}"
    echo -e "docker run -p 8080:8080 image-analyzer:latest"
    echo ""
    echo -e "${CYAN}# Deploy to Google Cloud:${NC}"
    echo -e "./scripts/build_and_deploy.sh"
    echo ""

    print_success "🐳 Dockerfiles are properly configured and ready for deployment!"
}

# Run main function
main "$@"