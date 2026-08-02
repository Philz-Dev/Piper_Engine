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

#SERVICES=("manager" "controller" "servers" "services" "worker" "runner-node" "runner-python")
SERVICES=("worker")

# 1. Build & Push Loop
for SERVICE in "${SERVICES[@]}"; do
    IMAGE="ghcr.io/${USERNAME}/piper-${SERVICE}"
    
    echo "📦 Building ${IMAGE}:${VERSION}..."
    
    # FIXED: Removed extra quote and cleaned up tagging
    #docker build -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" -f "${SERVICE}/Dockerfile" .
    docker build --network=host -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" -f "${SERVICE}/Dockerfile" .
    
    echo "📤 Pushing to GHCR..."
    docker push "${IMAGE}:${VERSION}"
    docker push "${IMAGE}:latest"
    echo "------------------------------------------------"
done

# 2. Cleanup Old Environment
echo "🧹 Cleaning up old containers..."
docker rm -f piper-manager piper-controller piper-frontend piper-db piper-redis piper-servers piper-service 2>/dev/null || true

# 3. Verify / Launch Locally
# NOTE: Usually you'd only run the Manager locally for testing
echo "🚀 Launching Piper Manager for verification..."
docker run -d \
  --name piper-manager \
  --network piper-network \
  -p 8080:8080 \
  "ghcr.io/${USERNAME}/piper-manager:${VERSION}"

echo "✅ Release ${VERSION} is officially live and Manager is running!"