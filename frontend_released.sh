#!/bin/bash
# 🚀 Piper Engine Release Script (Stable MINGW64 Version)

set -e 

VERSION=$1

if [ -z "$VERSION" ]; then
  echo "❌ Error: Please specify a version (e.g., ./release.sh v1)"
  exit 1
fi

# Configuration
export DOCKER_BUILDKIT=1
USERNAME="philz-dev"
SERVICES=("servers" "services" "controller" "worker" "manager")

# 1. Build & Push Loop
for SERVICE in "${SERVICES[@]}"; do
    IMAGE="ghcr.io/${USERNAME}/piper-${SERVICE}"
    
    echo "📦 Building ${IMAGE}:${VERSION}..."
    
    # FIXED: Removed extra quote and cleaned up tagging
    docker build -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" -f "${SERVICE}/Dockerfile" .
    #docker build --network=host -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" -f "${SERVICE}/Dockerfile" ./$SERVICE
    
    echo "📤 Pushing to GHCR..."
    docker push "${IMAGE}:${VERSION}"
    docker push "${IMAGE}:latest"
    echo "------------------------------------------------"
done

echo "✅ Release ${VERSION} is officially live and Manager is running!"