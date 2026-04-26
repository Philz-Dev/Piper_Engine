#!/bin/bash
# 🚀 Piper Engine Bootstrap: High-Speed Provisioning (Global Persistence Version)
set -e

# ✅ GLOBAL FIX: Prevent Git Bash from mangling Windows paths into Linux paths
export MSYS_NO_PATHCONV=1

echo "------------------------------------------------"
echo "   PIPER ENGINE: System Initialization Starting  "
echo "------------------------------------------------"

# 1. ⚡ CREDENTIALS ⚡
if [ -f .env ]; then
    sed -i 's/@piper-db:/@db:/g' .env || true
    DB_PASSWORD=$(grep DATABASE_URL .env | sed -e 's|.*//[^:]*:\([^@]*\)@.*|\1|')
else
    echo "📌 Generating fresh credentials..."
    DB_PASSWORD=$(openssl rand -hex 12 2>/dev/null || echo "piper_$(date +%s)")
    echo "DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data" > .env
fi

# ✅ WINDOWS VS LINUX COMPOSE LOGIC
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    DB_VOLUMES="- ./piper_db_data:/var/lib/postgresql/data"
    HOST_PROJECT_PATH=$(pwd -W)
    PLATFORM="windows"
else
    HOST_PROJECT_PATH=$(pwd)
    DB_VOLUMES="- ./piper_db_data:/var/lib/postgresql/data
      - /var/run/docker.sock:/var/run/docker.sock"
    PLATFORM="linux"
fi
echo "📍 Host Project Path: $HOST_PROJECT_PATH ($PLATFORM)"

COMPOSE_CONFIG=$(cat <<EOF
services:
  # --- INFRASTRUCTURE (No Auto-Updates) ---
  db:
    image: postgres:15-alpine
    container_name: piper-db
    restart: always
    environment:
      - POSTGRES_USER=piper_admin
      - POSTGRES_PASSWORD=$DB_PASSWORD
      - POSTGRES_DB=piper_data
    ports:
      - "5432:5432"
    volumes:
      $DB_VOLUMES
    networks:
      piper-network:
        aliases:
          - db

  redis-broker:
    image: redis:7-alpine
    container_name: piper-redis
    restart: always
    ports:
      - "6379:6379"
    networks:
      piper-network:
        aliases:
          - redis-broker

  # --- AUTO-UPDATER ---
  watchtower:
    image: containrrr/watchtower
    container_name: piper-watchtower
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: --label-enable --interval 300 --cleanup
    networks:
      - piper-network

  # --- PIPER CUSTOM SERVICES (With Auto-Updates) ---
  piper-manager:
    image: ghcr.io/philz-dev/piper-manager:v1
    container_name: piper-engine-manager
    restart: always
    dns:
      - 8.8.8.8
      - 1.1.1.1
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    environment:
      - DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data
      - MASTER_PASSWORD=$MASTER_PASSWORD
      - PYTHONPATH=/app
    volumes:
      - ./.env:/app/.env
      - piper_storage:/app/piper_storage
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/app
    networks:
      - piper-network
    # command: run

  piper-controller:
    image: ghcr.io/philz-dev/piper-controller:v1
    container_name: piper-engine-controller
    restart: always
    entrypoint: ["python", "/app/controller/watcher.py"]
    ports:
      - "8001:8001"
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    environment:
      - DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data
      - MASTER_PASSWORD=$MASTER_PASSWORD
      - PYTHONPATH=/app/controller
      - HOST_PROJECT_PATH=$HOST_PROJECT_PATH
    volumes:
      - ./.env:/app/.env
      - piper_storage:/app/piper_storage
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - piper-network
      
  piper-servers:
    image: ghcr.io/philz-dev/piper-servers:v1
    container_name: piper-engine-servers
    restart: always
    entrypoint: ["python", "/app/controller/watcher.py"]
    ports:
      - "8002:8002"
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    environment:
      - DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data
      - MASTER_PASSWORD=$MASTER_PASSWORD
      - PYTHONPATH=/app/services
    volumes:
      - ./.env:/app/.env
      - piper_storage:/app/piper_storage
    networks:
      - piper-network
    
  piper-services:
    image: ghcr.io/philz-dev/piper-services:v1
    container_name: piper-engine-services
    restart: always
    entrypoint: ["python", "/app/services/main.py"]
    ports:
      - "8003:8003"
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    environment:
      - DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data
      - MASTER_PASSWORD=$MASTER_PASSWORD
      - PYTHONPATH=/app
    volumes:
      - ./.env:/app/.env
      - piper_storage:/app/piper_storage
      - ./.piper_config:/app/.piper_config
    networks:
      - piper-network
    command: python -m services.main
  
networks:
  piper-network:
    name: piper-network

volumes:
  piper_storage:
    name: piper_storage
EOF
)

# 2. 🧹 THE CLEANUP FIX (Added piper_storage removal)
echo "🧹 Cleaning up old networks, volumes, and containers..."
docker rm -f piper-db piper-redis piper-watchtower piper-engine-manager piper-engine-controller piper-engine-frontend piper-engine-servers piper-engine-services 2>/dev/null || true
docker network rm piper-network 2>/dev/null || true
docker volume rm piper_storage 2>/dev/null || true

# --- Infrastructure Creation ---
#docker network create piper-network 2>/dev/null || true
docker volume create piper_storage 2>/dev/null || true

# 4. Global Command Setup
echo "🔗 Setting up Global CLI..."
cat <<'EOF' > ./piper_wrapper
#!/bin/bash
export MSYS_NO_PATHCONV=1
DOCKER_BIN="docker"

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    [ -t 0 ] && DOCKER_BIN="winpty docker"
    DOCKER_OPTS="-e DOCKER_HOST=tcp://host.docker.internal:2375"
else
    DOCKER_OPTS="-v /var/run/docker.sock:/var/run/docker.sock"
fi

# ✅ THE RUN COMMAND (Added // for Git Bash path protection)
$DOCKER_BIN run --rm -it \
    $DOCKER_OPTS \
    -v "/$(pwd):/app" \
    -p 8080:8080 \
    --network piper-network \
    --env-file .env \
    ghcr.io/philz-dev/piper-manager:v1 "$@"
EOF

# Install to path
INSTALL_DIR="$HOME/piper_bin"
mkdir -p "$INSTALL_DIR"
mv ./piper_wrapper "$INSTALL_DIR/piper"
chmod +x "$INSTALL_DIR/piper"

if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo "export PATH=\"\$HOME/piper_bin:\$PATH\"" >> ~/.bash_profile
fi

export PATH="$INSTALL_DIR:$PATH"
hash -r

# 5. ⚙️ STARTING DATABASE
echo "⚙️  Starting Core Database..."
echo "$COMPOSE_CONFIG" | docker-compose -f - up -d --remove-orphans

echo "⏳ Waiting for Database..."
until docker exec piper-db pg_isready -U piper_admin >/dev/null 2>&1; do
    echo -n "."
    sleep 2
done

# 6. HANDSHAKE
echo -e "\n🚀 Running Core Initialization..."
"$INSTALL_DIR/piper" init
alias piper="$INSTALL_DIR/piper"

echo "------------------------------------------------"
echo "✅ SUCCESS: Piper Engine Online"
echo "------------------------------------------------"