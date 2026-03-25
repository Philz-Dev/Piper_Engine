#!/bin/bash
# 🚀 Piper Engine Bootstrap: The Automated Agency Setup

set -e # Exit immediately if a command fails

echo "------------------------------------------------"
echo "  PIPER ENGINE: System Initialization Starting  "
echo "------------------------------------------------"

# 1. Environment Check: Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "📌 No .env file found. Let's configure your database."
    read -p "Enter your PostgreSQL URL (e.g., postgresql://user:pass@localhost:5432/db): " db_url
    echo "DATABASE_URL=$db_url" > .env
    echo "✅ .env created successfully."
fi

# 2. Dependency Check: Install Docker if missing
if ! [ -x "$(command -v docker)" ]; then
    echo "📦 Docker not found. Installing now..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    echo "✅ Docker installed."
else
    echo "✅ Docker is already installed."
fi

# 3. Pull the Engine
echo "🚚 Pulling the latest Piper Engine image..."
docker pull ghcr.io/philz-dev/piper-engine:v1

# 4. The Internal Handshake: Run piper init
echo "⚙️  Running Internal Core Initialization..."
# This triggers your Python 'init' function to set up DB tables silently
docker run --rm --env-file .env ghcr.io/philz-dev/piper-engine:v1 piper init

# 5. Final Launch
if [ -f docker-compose.yml ]; then
    echo "🚀 Launching services with Docker Compose..."
    docker-compose up -d
    echo "------------------------------------------------"
    echo "  SUCCESS: Piper Engine is now running!         "
    echo "------------------------------------------------"
else
    echo "⚠️  Setup finished, but no docker-compose.yml found."
    echo "You can now run your engine using: docker run ..."
fi