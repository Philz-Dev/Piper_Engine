#!/bin/bash
# 🚀 Stretis Engine Bootstrap: High-Speed Provisioning (Adaptive Environment Variant)
#set -e

# ✅ GLOBAL FIX: Prevent Git Bash from mangling Windows paths into Linux paths
export MSYS_NO_PATHCONV=1

echo "------------------------------------------------"
echo "   STRETIS ENGINE: System Initialization Starting    "
echo "------------------------------------------------"

INSTALL_CODE=$1
if [ -z "$INSTALL_CODE" ]; then
    echo "❌ Error: Please provide your installation code: sh setup.sh <INSTALL_CODE>"
    exit 1
fi

CENTRAL_API="https://piper-backend-production.up.railway.app"

echo "------------------------------------------------"
echo "   STRETIS ENGINE: Querying Configuration via Code "
echo "------------------------------------------------"

echo "📡 Fetching user credentials and domain from Central Registry..."

CONFIG_JSON=$(curl -s "$CENTRAL_API/api/v1/engine/config/$INSTALL_CODE")

if [ -z "$CONFIG_JSON" ] || [ "$CONFIG_JSON" == "null" ]; then
    echo "❌ ERROR: Invalid or expired installation code."
    exit 1
fi

# ✅ Pure Bash JSON field parser (No Python required)
parse_json_field() {
    echo "$1" | grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -n 1 | sed 's/.*:"\(.*\)"/\1/'
}

USER_EMAIL=$(parse_json_field "$CONFIG_JSON" "email")
USER_DOMAIN=$(parse_json_field "$CONFIG_JSON" "domain")
USER_ID=$(parse_json_field "$CONFIG_JSON" "user_id")
INSTALL_TOKEN=$(parse_json_field "$CONFIG_JSON" "install_token")
[ -z "$INSTALL_TOKEN" ] && INSTALL_TOKEN="$INSTALL_CODE"

if [ -z "$USER_EMAIL" ] || [ -z "$USER_DOMAIN" ] || [ -z "$USER_ID" ]; then
    echo "❌ ERROR: Failed to resolve complete credentials from installation code."
    exit 1
fi

echo "✅ Email Retrieved: $USER_EMAIL"
echo "✅ Domain Retrieved: $USER_DOMAIN"
echo "✅ User ID Retrieved: $USER_ID"

# 🔍 INFRASTRUCTURE DETECTION: Identify if running on a local machine (laptop/desktop) or VPS
echo "🕵️‍♂️ Analyzing hardware infrastructure environment..."
DETECTED_ENV="cloud" # Default fallback assumption

# Check 1: Check for explicit battery sub-systems (Laptops/Local Desktops)
if [ -d "/sys/class/power_supply/BAT0" ] || [ -d "/sys/class/power_supply/BAT1" ]; then
    DETECTED_ENV="local"
# Check 2: Check OS Type for local development environments (Windows Git Bash / MacOS Devs)
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "darwin"* ]]; then
    DETECTED_ENV="local"
# Check 3: Check for Cloud Provider Metadata endpoints (if it times out, it's a home network/private environment)
else
    # Query a public lookup engine to verify if the IP space belongs to a known consumer ISP or cloud data center
    ISP_OR_CLOUD=$(curl -s --max-time 3 https://ipapi.co/asn/ || echo "unknown")
    if [[ "$ISP_OR_CLOUD" =~ "Hosting" || "$ISP_OR_CLOUD" =~ "Data" || "$ISP_OR_CLOUD" =~ "Cloud" ]]; then
        DETECTED_ENV="cloud"
    else
        # If running via a standard Linux consumer installation or custom private network
        DETECTED_ENV="local"
    fi
fi

echo "📍 Infrastructure Verified: Auto-assigning engine mode to -> [$DETECTED_ENV]"

# 0.1 HIDE THE NGINX CONFIG
echo "🔒 Configuring Secure Nginx (Hidden)..."
mkdir -p ./.piper_internal

cat <<EOF > ./.piper_internal/nginx.conf
events { worker_connections 1024; }
http {
    # Check for a specific secret header
    map \$http_x_piper_secret \$is_authorized {
        default "0";
        "MY_SUPER_SECRET_KEY" "1";
    }

    server {
        listen 80;
        server_name $USER_DOMAIN;

        location / {
            # If header is missing or wrong, deny access
            if (\$is_authorized = "0") {
                return 403;
            }
            proxy_pass http://piper-engine-servers:8099;
            proxy_set_header Host \$host;
        }
    }
}
EOF

chmod 600 ./.piper_internal/nginx.conf
echo "✅ Nginx config generated and hidden for $USER_DOMAIN."

# 1. ⚡ CREDENTIALS & ENVIRONMENT SETUP ⚡
if [ -f .env ]; then
    sed -i 's/@piper-db:/@db:/g' .env || true
    DB_PASSWORD=$(grep DATABASE_URL .env | sed -e 's|.*//[^:]*:\([^@]*\)@.*|\1|')
else
    echo "📌 Generating fresh credentials..."
    DB_PASSWORD=$(openssl rand -hex 12 2>/dev/null || echo "piper_$(date +%s)")
    echo "DATABASE_URL=postgresql://postgres:$DB_PASSWORD@db:5432/piper_data" > .env
fi

# ✅ FIX: Inject User Identity and API tokens directly into .env
sed -i '/USER_ID=/d' .env 2>/dev/null || true
sed -i '/PIPER_API_KEY=/d' .env 2>/dev/null || true
sed -i '/INSTALL_TOKEN=/d' .env 2>/dev/null || true

echo "USER_ID=$USER_ID" >> .env
echo "PIPER_API_KEY=$INSTALL_TOKEN" >> .env
echo "INSTALL_TOKEN=$INSTALL_TOKEN" >> .env

# ✅ FIX: Force-inject WebRTC local interface bypass into .env
if grep -q "AIOICE_SKIP_INTERFACES" .env; then
    sed -i "s|AIOICE_SKIP_INTERFACES=.*|AIOICE_SKIP_INTERFACES=eth0,docker0|g" .env
else
    echo "AIOICE_SKIP_INTERFACES=eth0,docker0" >> .env
fi

# Ensure NGROK_AUTHTOKEN exists
if ! grep -q "NGROK_AUTHTOKEN" .env; then
    echo "------------------------------------------------"
    echo "🔑 SETUP: Ngrok Authtoken required for tunnel."
    echo "   1. Login to https://dashboard.ngrok.com/"
    echo "   2. Copy your 'Your Authtoken'"
    echo "------------------------------------------------"
    read -p "Paste your Ngrok Authtoken here: " USER_TOKEN
    echo "NGROK_AUTHTOKEN=$USER_TOKEN" >> .env
    echo "✅ Token saved to .env"
fi

# Reload environment
export $(grep -v '^#' .env | xargs)

# ✅ WINDOWS VS LINUX COMPOSE LOGIC
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    DB_VOLUMES="- ./piper_db_data:/var/lib/postgresql/data"
    HOST_PROJECT_PATH=$(pwd -W)
    PLATFORM="windows"
    INTERNAL_DOCKER_HOST="unix:///var/run/docker.sock"
    SERVER_VOLUMES="- ./.env:/app/.env
      - piper_storage:/app/piper_storage
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/app"
else
    HOST_PROJECT_PATH=$(pwd)
    DB_VOLUMES="- ./piper_db_data:/var/lib/postgresql/data
      - /var/run/docker.sock:/var/run/docker.sock"
    PLATFORM="linux"
    INTERNAL_DOCKER_HOST="unix:///var/run/docker.sock"
    SERVER_VOLUMES="- ./.env:/app/.env
      - piper_storage:/app/piper_storage
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/app"
fi
echo "📍 Host Project Path: $HOST_PROJECT_PATH ($PLATFORM)"

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    echo "🔧 Optimizing Docker for Windows..."
    DOCKER_SETTINGS="$APPDATA/Docker/settings-store.json"
    if [ -f "$DOCKER_SETTINGS" ]; then
        powershell.exe -Command "\$path = \"\$env:APPDATA\Docker\settings-store.json\"; \$settings = Get-Content \$path | ConvertFrom-Json; if (\$settings.exposeDockerAPIOnTCP2375 -eq \$false) { \$settings.exposeDockerAPIOnTCP2375 = \$true; \$settings | ConvertTo-Json | Set-Content \$path; Write-Host '✅ TCP Daemon Exposed. Restarting Docker...'; Stop-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue; Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'; }"
    fi
fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🍎 Optimizing Docker for macOS..."
    if [ ! -S /var/run/docker.sock ]; then sudo ln -s -f "$HOME/.docker/run/docker.sock" /var/run/docker.sock; fi
    DOCKER_SETTINGS_MAC="$HOME/Library/Group Containers/group.com.docker/settings-store.json"
    if [ -f "$DOCKER_SETTINGS_MAC" ]; then
        python3 -c "import json, os; path=os.path.expanduser('$DOCKER_SETTINGS_MAC'); with open(path, 'r') as f: data=json.load(f); data['allowDefaultSocket']=True; with open(path, 'w') as f: json.dump(data, f)"
    fi
fi

COMPOSE_CONFIG=$(cat <<EOF
services:
  db:
    image: postgres:15-alpine
    container_name: piper-db
    restart: always
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U piper_admin -d piper_data"]
      interval: 5s
      timeout: 5s
      retries: 5
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
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 5
    networks:
      piper-network:
        aliases:
          - redis-broker

  watchtower:
    image: containrrr/watchtower
    container_name: piper-watchtower
    restart: always
    environment:
      - DOCKER_API_VERSION=1.41
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: --label-enable --interval 300 --cleanup
    networks:
      - piper-network

  piper-manager:
    image: ghcr.io/philz-dev/piper-manager:v1
    container_name: piper-engine-manager
    restart: always
    extra_hosts:
      - "host.docker.internal:host-gateway"
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

  piper-controller:
    image: ghcr.io/philz-dev/piper-controller:v1
    container_name: piper-engine-controller
    restart: always
    entrypoint: ["python", "/app/controller/watcher.py"]
    depends_on:
      redis-broker:
        condition: service_healthy
    ports:
      - "8001:8001"
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    environment:
      - DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data
      - MASTER_PASSWORD=$MASTER_PASSWORD
      - PYTHONPATH=/app/controller
      - HOST_PROJECT_PATH=$HOST_PROJECT_PATH
      - PYTHONUNBUFFERED=1
      - DOCKER_HOST=$INTERNAL_DOCKER_HOST
      - INSTALL_TOKEN=$INSTALL_TOKEN
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./.env:/app/.env
      $SERVER_VOLUMES
      - ./templates:/app/templates
      - ./.piper_config:/app/.piper_config
    networks:
      - piper-network

  piper-runner-python:
    image: ghcr.io/philz-dev/piper-python_runner:v1
    container_name: piper-runner-python-live
    restart: always
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    volumes:
      - \${HOST_PROJECT_PATH}:/app
    networks:
      - piper-network
    entrypoint: ["tail", "-f", "/dev/null"]

  piper-runner-node:
    image: ghcr.io/philz-dev/piper-javascript_runner:v1
    container_name: piper-runner-node-live
    restart: always
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    volumes:
      - \${HOST_PROJECT_PATH}:/app
    networks:
      - piper-network
    entrypoint: ["tail", "-f", "/dev/null"]

  nginx:
    image: nginx:alpine
    container_name: piper-nginx
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./.piper_internal/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/webroot:/var/www/certbot
    networks:
      - piper-network
    depends_on:
      - piper-servers
 
  certbot:
    image: certbot/certbot
    container_name: piper-certbot
    volumes:
      - ./nginx/certs:/etc/letsencrypt
      - ./nginx/webroot:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait \$\${!}; done;'"
    networks:
      - piper-network

  piper-frontend:
    image: ghcr.io/philz-dev/piper-frontend:latest
    container_name: piper-frontend
    restart: always
    ports:
      - "3000:3000"  # Assuming your frontend serves on port 80
    environment:
      - API_URL=http://piper-engine-servers:8099
      - INSTALL_TOKEN=$INSTALL_TOKEN
      - NEXT_PUBLIC_ENGINE_MODE=$DETECTED_ENV 
    networks:
      - piper-network
    depends_on:
      - piper-servers
      
  piper-servers:
    image: ghcr.io/philz-dev/piper-servers:v1
    container_name: piper-engine-servers
    restart: always
    dns:
      - 8.8.8.8
      - 8.8.4.4
    extra_hosts:
      - "host.docker.internal:host-gateway"
    entrypoint: ["python", "/app/servers/main.py"]
    ports:
      - "8099:8099"
      - "50000-50050:50000-50050/udp" # ⚡ WebRTC predictable port channel tunnel mapped here
      - "50000-50011:50000-50011/tcp"
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    env_file:
      - .env
    environment:
      - DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data
      - MASTER_PASSWORD=$MASTER_PASSWORD
      - PYTHONPATH=/app
      - DOCKER_HOST=$INTERNAL_DOCKER_HOST
      - ENGINE_MODE=$DETECTED_ENV
      - AIOICE_SKIP_INTERFACES=eth0,docker0
      - USER_ID=$USER_ID
      - PIPER_API_KEY=$INSTALL_TOKEN
      - INSTALL_TOKEN=$INSTALL_TOKEN
      - HOST_PROJECT_PATH=$HOST_PROJECT_PATH
    volumes:
      $SERVER_VOLUMES
    networks:
      - piper-network
    command: python -m servers.main
    
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

# 2. 🧹 THE CLEANUP
echo "🧹 Cleaning up old networks, volumes, and containers..."
docker rm -f piper-db piper-redis piper-watchtower piper-engine-manager piper-engine-controller piper-engine-servers piper-engine-services piper-runner-python-live piper-runner-node-live piper-tunnel 2>/dev/null || true
docker rm -f $(docker ps -aq --filter label=service=piper-worker)
docker network rm piper-network 2>/dev/null || true
docker volume create piper_storage 2>/dev/null || true

# 4. Global Command Setup
echo "🔗 Setting up Global CLI..."
cat <<'EOF' > ./piper_wrapper
#!/bin/bash
export MSYS_NO_PATHCONV=1
DOCKER_BIN="docker"
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    [ -t 0 ] && DOCKER_BIN="winpty docker"
    DOCKER_OPTS="-e DOCKER_HOST=tcp://host.docker.internal:2375 -e DOCKER_API_VERSION=1.41"
    DNS_BRIDGE="--add-host host.docker.internal:host-gateway"
else
    DOCKER_OPTS="-v /var/run/docker.sock:/var/run/docker.sock"
    DNS_BRIDGE=""
fi
$DOCKER_BIN run --rm -it $DOCKER_OPTS $DNS_BRIDGE -v "/$(pwd):/app" -p 8080:8080 --network piper-network --env-file .env ghcr.io/philz-dev/piper-manager:v1 "$@"
EOF
INSTALL_DIR="$HOME/piper_bin"
mkdir -p "$INSTALL_DIR"
mv ./piper_wrapper "$INSTALL_DIR/piper"
chmod +x "$INSTALL_DIR/piper"
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then echo "export PATH=\"\$HOME/piper_bin:\$PATH\"" >> ~/.bash_profile; fi
export PATH="$INSTALL_DIR:$PATH"
hash -r

# 5. ⚙️ STARTING DATABASE & SERVICES
echo "⚙️  Starting Core Engine..."
echo "$COMPOSE_CONFIG" | docker-compose -f - up -d --remove-orphans

echo "⏳ Waiting for Database connection layer to completely settle..."
until docker exec piper-db pg_isready -U piper_admin -d piper_data >/dev/null 2>&1; do
    echo -n "."
    sleep 2
done

until docker exec piper-db psql -U piper_admin -d piper_data -c "SELECT 1;" >/dev/null 2>&1; do
    echo -n "⚙️"
    sleep 2
done

echo -e "\n✅ Database Engine is accepting operations!"

# 6. HANDSHAKE
echo -e "\n🚀 Running Core Initialization..."
"$INSTALL_DIR/piper" init
alias piper="$INSTALL_DIR/piper"

# 7. 🔗 REGISTERING VIA TUNNEL
echo "📡 Registering Engine with Piper Cloud..."

TUNNEL_URL=""
echo "⏳ Establishing secure tunnel (this may take a few seconds)..."

echo -e "\n🌍 Tunnel Active: $TUNNEL_URL"

PIPER_API_URL="$CENTRAL_API/api/v1/engine/register"

echo "📡 Checking Piper Engine API Health..."

# ✅ MODIFIED: Dynamic status routing targeting the updated FastAPI structure
echo "📡 Signaling Central API that orchestration engine installation is successful..."
STATUS_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$CENTRAL_API/api/v1/engine/update-status/$INSTALL_CODE?installation_type=$DETECTED_ENV&status=true")

if [ "$STATUS_RESPONSE" == "200" ]; then
    echo "✅ Central Registry updated: Status is now ACTIVE ($DETECTED_ENV)."
else
    echo "⚠️ Warning: Failed to update status in Central Registry (Status $STATUS_RESPONSE)"
fi

echo -e "\n✅ Piper Engine API is LIVE and responding!"
echo "------------------------------------------------"
echo "✅ SUCCESS: Piper Engine Online & Linked"
echo "------------------------------------------------"