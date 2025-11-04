#!/bin/bash

# Script to ensure Dockerfiles are properly configured
# Usage: ./create_dockerfiles.sh

set -e

echo "🐳 Checking Dockerfiles..."

# Check if main Dockerfile exists
if [ ! -f "Dockerfile" ]; then
    echo "❌ Main Dockerfile not found!"
    exit 1
fi

# Check if worker Dockerfile exists
if [ ! -f "Dockerfile.worker" ]; then
    echo "❌ Worker Dockerfile not found!"
    exit 1
fi

echo "✅ Main Dockerfile exists"
echo "✅ Worker Dockerfile exists"

# Validate Dockerfiles have proper structure
if ! grep -q "FROM python" Dockerfile; then
    echo "❌ Main Dockerfile doesn't appear to be a Python-based image"
    exit 1
fi

if ! grep -q "FROM python" Dockerfile.worker; then
    echo "❌ Worker Dockerfile doesn't appear to be a Python-based image"
    exit 1
fi

echo "✅ Dockerfiles validated successfully"