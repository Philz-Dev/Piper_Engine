#!/bin/bash
# 🚀 Stretis Engine Bootstrap: High-Speed Provisioning (Bare / Offline Mode)
set -e

# ✅ GLOBAL FIX: Prevent Git Bash from mangling Windows paths into Linux paths
export MSYS_NO_PATHCONV=1

echo "------------------------------------------------"
echo "   STRETIS ENGINE: System Initialization Starting    "
echo "------------------------------------------------"

# 🧰 PREFLIGHT: fail fast with a clear message instead of dying deep in the script
echo "🧰 Checking required tools..."
MISSING_DEPS=0
for cmd in docker openssl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "❌ Required tool not found: $cmd"
        MISSING_DEPS=1
    fi
done

# Support both `docker compose` (v2 plugin) and legacy `docker-compose`
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
else
    echo "❌ Neither 'docker compose' nor 'docker-compose' is available."
    MISSING_DEPS=1
fi

# 🛠️ FIX: Compose's project name — the identity it uses to decide
# whether an existing network/volume belongs to THIS setup or someone
# else's — defaults to the current directory's BASENAME when nothing
# pins it explicitly. That means renaming or relocating the project
# folder (exactly what moving everything into automation_engine/ did)
# silently changes Compose's own idea of "who owns piper-network and
# piper_storage", even though nothing about the actual infrastructure
# changed. The result: "exists but was not created for project ..."
# warnings, Compose reusing stale/mismatched resources instead of
# cleanly-owned ones, and containers that depend on that network
# (piper-engine-servers, reported crash-looping) failing to connect
# correctly. Pinning a fixed name here — via `-p`, added to
# DOCKER_COMPOSE itself so every call site below picks it up
# automatically — makes this identity permanent regardless of what
# directory the script is ever run from or renamed to in the future.
COMPOSE_PROJECT_NAME="piper_engine"
DOCKER_COMPOSE="$DOCKER_COMPOSE -p $COMPOSE_PROJECT_NAME"

if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker daemon is not reachable. Is Docker Desktop / the docker service running?"
    MISSING_DEPS=1
fi

if [ "$MISSING_DEPS" -eq 1 ]; then
    echo "Install/start the missing tool(s) above, then rerun this script."
    exit 1
fi
echo "✅ All required tools found (using: $DOCKER_COMPOSE)"

# 📌 Local Bare Configuration (No internet verification required)
USER_EMAIL="admin@local.host"
USER_DOMAIN="localhost"
USER_ID="1"

echo "✅ Email Configured: $USER_EMAIL"
echo "✅ Domain Configured: $USER_DOMAIN"
echo "✅ User ID Configured: $USER_ID"

# 🔍 INFRASTRUCTURE DETECTION: Identify if running on a local machine (laptop/desktop) or VPS
echo "🕵️‍♂️ Analyzing hardware infrastructure environment..."
DETECTED_ENV="local" # Default offline fallback

if [ -d "/sys/class/power_supply/BAT0" ] || [ -d "/sys/class/power_supply/BAT1" ]; then
    DETECTED_ENV="local"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "darwin"* ]]; then
    DETECTED_ENV="local"
else
    DETECTED_ENV="cloud"
fi

echo "📍 Infrastructure Verified: Auto-assigning engine mode to -> [$DETECTED_ENV]"

# 1. ⚡ CREDENTIALS & ENVIRONMENT SETUP ⚡
# Generate/reuse a real INSTALL_TOKEN and PIPER_ADMIN_SECRET instead of hardcoding placeholders
if [ -f .env ]; then
    sed -i 's/@piper-db:/@db:/g' .env || true
    # Self-heal .env files generated before the piper_admin username fix
    # below — same migration pattern as the @piper-db: line above.
    sed -i 's|postgresql://postgres:|postgresql://piper_admin:|g' .env || true
    DB_PASSWORD=$(grep DATABASE_URL .env | sed -e 's|.*//[^:]*:\([^@]*\)@.*|\1|')
else
    echo "📌 Generating fresh credentials..."
    DB_PASSWORD=$(openssl rand -hex 12 2>/dev/null || echo "piper_$(date +%s)")
    # 🛠️ FIX: was "postgres:$DB_PASSWORD" — the `db` service below is
    # actually initialized with POSTGRES_USER=piper_admin, not the
    # postgres superuser. The long-running containers never hit this
    # because their DATABASE_URL is hardcoded correctly to piper_admin
    # right in the compose environment: block, but `piper init` runs
    # as a separate one-off container via `docker run --env-file .env`
    # (see piper_wrapper below), which reads this file's value
    # directly — so it was connecting as a user that was never
    # created, and failing with "password authentication failed for
    # user \"postgres\"".
    echo "DATABASE_URL=postgresql://piper_admin:$DB_PASSWORD@db:5432/piper_data" > .env
fi

# Reuse an existing INSTALL_TOKEN/ADMIN_SECRET if present, otherwise generate real random ones.
# (No more hardcoded "local_install_token" / "MY_SUPER_SECRET_KEY" placeholders baked into images.)
if grep -q "^INSTALL_TOKEN=" .env 2>/dev/null; then
    INSTALL_TOKEN=$(grep "^INSTALL_TOKEN=" .env | cut -d= -f2-)
else
    INSTALL_TOKEN=$(openssl rand -hex 24 2>/dev/null || echo "local_$(date +%s)")
fi

if grep -q "^PIPER_ADMIN_SECRET=" .env 2>/dev/null; then
    PIPER_ADMIN_SECRET=$(grep "^PIPER_ADMIN_SECRET=" .env | cut -d= -f2-)
else
    PIPER_ADMIN_SECRET=$(openssl rand -hex 24 2>/dev/null || echo "secret_$(date +%s)")
fi

if ! grep -q "^MASTER_PASSWORD=" .env 2>/dev/null; then
    MASTER_PASSWORD=$(openssl rand -hex 16 2>/dev/null || echo "master_$(date +%s)")
    echo "MASTER_PASSWORD=$MASTER_PASSWORD" >> .env
else
    MASTER_PASSWORD=$(grep "^MASTER_PASSWORD=" .env | cut -d= -f2-)
fi

sed -i '/^USER_ID=/d' .env 2>/dev/null || true
sed -i '/^PIPER_API_KEY=/d' .env 2>/dev/null || true
sed -i '/^INSTALL_TOKEN=/d' .env 2>/dev/null || true
sed -i '/^PIPER_ADMIN_SECRET=/d' .env 2>/dev/null || true

echo "USER_ID=$USER_ID" >> .env
echo "PIPER_API_KEY=$INSTALL_TOKEN" >> .env
echo "INSTALL_TOKEN=$INSTALL_TOKEN" >> .env
echo "PIPER_ADMIN_SECRET=$PIPER_ADMIN_SECRET" >> .env

if grep -q "AIOICE_SKIP_INTERFACES" .env; then
    sed -i "s|AIOICE_SKIP_INTERFACES=.*|AIOICE_SKIP_INTERFACES=eth0,docker0|g" .env
else
    echo "AIOICE_SKIP_INTERFACES=eth0,docker0" >> .env
fi

if ! grep -q "NGROK_AUTHTOKEN" .env; then
    echo "------------------------------------------------"
    echo "🔑 SETUP: Ngrok Authtoken required for tunnel (Optional)."
    echo "------------------------------------------------"
    read -p "Paste your Ngrok Authtoken here (or press Enter to skip): " USER_TOKEN
    if [ -n "$USER_TOKEN" ]; then
        echo "NGROK_AUTHTOKEN=$USER_TOKEN" >> .env
        echo "✅ Token saved to .env"
    else
        echo "NGROK_AUTHTOKEN=disabled" >> .env
    fi
fi

# 🔌 Nginx host ports — configurable because 80/443 are frequently taken on
# Windows hosts (IIS, Skype, VPN clients, other containers). Override by
# setting NGINX_HTTP_PORT / NGINX_HTTPS_PORT in .env before rerunning.
if grep -q "^NGINX_HTTP_PORT=" .env 2>/dev/null; then
    NGINX_HTTP_PORT=$(grep "^NGINX_HTTP_PORT=" .env | cut -d= -f2-)
else
    NGINX_HTTP_PORT=80
    echo "NGINX_HTTP_PORT=80" >> .env
fi
if grep -q "^NGINX_HTTPS_PORT=" .env 2>/dev/null; then
    NGINX_HTTPS_PORT=$(grep "^NGINX_HTTPS_PORT=" .env | cut -d= -f2-)
else
    NGINX_HTTPS_PORT=443
    echo "NGINX_HTTPS_PORT=443" >> .env
fi

export $(grep -v '^#' .env | xargs)

# 0.1 SECURE NGINX CONFIG — now uses the real generated secret, not a hardcoded placeholder
echo "🔒 Configuring Secure Nginx (Hidden)..."
mkdir -p ./.piper_internal

cat <<EOF > ./.piper_internal/nginx.conf
events { worker_connections 1024; }
http {
    # 🛠️ FIX: nginx's default map_hash_bucket_size (32 or 64 bytes, depending
    # on platform) is too small to hold PIPER_ADMIN_SECRET as a map key -
    # it's a 48-char hex string (openssl rand -hex 24), which exceeds the
    # default bucket size once nginx's internal alignment is factored in.
    # Without this, nginx fails at startup with "could not build map_hash,
    # you should increase map_hash_bucket_size" and restart-loops forever.
    # 128 comfortably covers the current 48-char secret with room to spare.
    map_hash_bucket_size 128;

    map \$http_x_piper_secret \$is_authorized {
        default "0";
        "$PIPER_ADMIN_SECRET" "1";
    }

    server {
        listen 80;
        server_name $USER_DOMAIN;

        location / {
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

# ✅ OS-SPECIFIC PATH MAPPINGS
# NOTE: these are plain strings WITHOUT a leading "- " — the compose YAML below
# supplies the dash itself. (The double-dash here was the bug causing
# "services.db.volumes.0 must be a string".)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    DB_VOLUMES="./piper_db_data:/var/lib/postgresql/data"
    HOST_PROJECT_PATH=$(pwd -W)
    PLATFORM="windows"
    SERVER_VOLUMES="- ./.env:/app/.env
      - piper_storage:/app/piper_storage
      - .:/app"
else
    HOST_PROJECT_PATH=$(pwd)
    DB_VOLUMES="./piper_db_data:/var/lib/postgresql/data"
    PLATFORM="linux"
    SERVER_VOLUMES="- ./.env:/app/.env
      - piper_storage:/app/piper_storage
      - .:/app"
fi
echo "📍 Host Project Path: $HOST_PROJECT_PATH ($PLATFORM)"

# Secure Internal Docker Host pointing to the Proxy container
INTERNAL_DOCKER_HOST="tcp://docker-proxy:2375"

COMPOSE_CONFIG=$(cat <<EOF
services:
  # 🛡️ Secure Docker Socket Proxy (Blocks host access, limits API surface)
  # NOTE: EXEC dropped to 0 — piper-controller/manager don't need to exec into
  # arbitrary containers via the Docker API. Flip back to 1 only if something breaks
  # and you've confirmed it actually needs exec.
  docker-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: piper-docker-proxy
    restart: always
    environment:
      - CONTAINERS=1
      - EXEC=0
      - IMAGES=1
      - INFO=1
      - PING=1
      - VERSION=1
      - POST=1
      - AUTH=1
      - NETWORKS=1
      - VOLUMES=1
      - BUILD=0
      - SERVICES=0
      - TASKS=0
      - SECRETS=0
      - CONFIGS=0
      - NODES=0
      - SWARM=0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - piper-network

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
    volumes:
      - $DB_VOLUMES
    networks:
      piper-network:
        aliases:
          - db

  redis-broker:
    image: redis:7-alpine
    container_name: piper-redis
    restart: always
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
      - DOCKER_HOST=$INTERNAL_DOCKER_HOST
      - DOCKER_API_VERSION=1.41
    command: --label-enable --interval 300 --cleanup
    networks:
      - piper-network

  piper-manager:
    image: ghcr.io/philz-dev/piper-manager:v1
    container_name: piper-engine-manager
    restart: always
    # 🛠️ FIX: this service connects to both db (DATABASE_URL) and
    # docker-proxy (DOCKER_HOST) at startup, but had no depends_on at
    # all — Compose started it in the same batch as piper-db, so its
    # first connection attempt raced against Postgres actually being
    # ready, lost that race, crashed, and sat in restart backoff. The
    # post-DB health check then caught it mid-restart and reported it
    # as failed, even though it would likely have recovered on its own
    # a few seconds later. piper-controller already does this correctly
    # below — mirroring that here.
    depends_on:
      db:
        condition: service_healthy
      docker-proxy:
        condition: service_started
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
      - DOCKER_HOST=$INTERNAL_DOCKER_HOST
    volumes:
      - ./.env:/app/.env
      - piper_storage:/app/piper_storage
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
      docker-proxy:
        condition: service_started
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
      - $HOST_PROJECT_PATH:/app
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
      - $HOST_PROJECT_PATH:/app
    networks:
      - piper-network
    entrypoint: ["tail", "-f", "/dev/null"]

  nginx:
    image: nginx:alpine
    container_name: piper-nginx
    restart: always
    ports:
      - "$NGINX_HTTP_PORT:80"
      - "$NGINX_HTTPS_PORT:443"
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
      - "50000-50050:50000-50050/udp"
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
# Stop gracefully first (gives Postgres a chance to checkpoint and shut down
# cleanly) before force-removing. `rm -f` alone SIGKILLs, which is what was
# causing crash recovery (and slow startup) on the next run.
# 🛠️ FIX: this list was missing piper-nginx and piper-certbot — two
# container_names the compose file below actually defines. Whichever of
# those already existed from a prior run was never cleaned up here, so
# `docker compose up` would hit a name conflict ("Conflict. The
# container name ... is already in use") trying to recreate it. Keeping
# this list in sync with every container_name in the compose file is the
# actual fix; missing any one of them reproduces the same failure for
# that container specifically.
# (piper-frontend was previously listed here too, on the belief that the
# compose file defines it — it does not; grep container_name: below and
# there is no such service. Harmless here since `rm -f` on a nonexistent
# name is a silent no-op, but see the SERVICES_TO_CHECK fix further down
# for where the identical stale belief was NOT harmless.)
docker stop -t 30 piper-db piper-redis piper-watchtower piper-docker-proxy piper-engine-manager piper-engine-controller piper-engine-servers piper-engine-services piper-runner-python-live piper-runner-node-live piper-nginx piper-certbot 2>/dev/null || true
docker rm -f piper-db piper-redis piper-watchtower piper-docker-proxy piper-engine-manager piper-engine-controller piper-engine-servers piper-engine-services piper-runner-python-live piper-runner-node-live piper-nginx piper-certbot 2>/dev/null || true
docker network rm piper-network 2>/dev/null || true
docker volume create piper_storage 2>/dev/null || true

# 3. Global Command Setup
echo "🔗 Setting up Global CLI..."
cat <<'EOF' > ./piper_wrapper
#!/bin/bash
export MSYS_NO_PATHCONV=1
DOCKER_BIN="docker"
# 🛠️ FIX: previously pointed DOCKER_HOST at host.docker.internal:2375, which
# (a) only works if Docker Desktop's insecure "expose daemon on tcp://localhost:2375"
#     setting is manually enabled - off by default, so this failed with
#     "Network is unreachable" for anyone who hadn't flipped it on, and
# (b) even when it does work, bypasses docker-proxy entirely, undoing the
#     socket-proxy hardening (EXEC=0/BUILD=0/etc.) used everywhere else in
#     this stack.
# Since this container already joins --network piper-network below, it can
# resolve docker-proxy by name via Docker's embedded DNS, same as every other
# service in the compose file. Route through that instead of the host daemon.
# Also note: any -e/--env flag here always wins over --env-file .env for the
# same variable, so DOCKER_HOST must be set correctly here rather than relying
# on .env to supply it.
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    [ -t 0 ] && DOCKER_BIN="winpty docker"
fi
DOCKER_OPTS="-e DOCKER_HOST=tcp://docker-proxy:2375 -e DOCKER_API_VERSION=1.41"
DNS_BRIDGE=""
$DOCKER_BIN run --rm -it $DOCKER_OPTS $DNS_BRIDGE -v "/$(pwd):/app" -p 8080:8080 --network piper-network --env-file .env ghcr.io/philz-dev/piper-manager:v1 "$@"
EOF
INSTALL_DIR="$HOME/piper_bin"
mkdir -p "$INSTALL_DIR"
mv ./piper_wrapper "$INSTALL_DIR/piper"
chmod +x "$INSTALL_DIR/piper"
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then echo "export PATH=\"\$HOME/piper_bin:\$PATH\"" >> ~/.bash_profile; fi
export PATH="$INSTALL_DIR:$PATH"
hash -r

# 4. ⚙️ STARTING DATABASE & SERVICES

# Validate the generated compose YAML BEFORE trying to pull/start anything —
# catches structural errors (like the volumes bug that bit earlier runs)
# with a clear message instead of a confusing failure mid-pull/up.
echo "🔎 Validating generated compose configuration..."
if ! echo "$COMPOSE_CONFIG" | $DOCKER_COMPOSE -f - config -q; then
    echo "❌ Generated docker-compose config is invalid. Aborting before touching containers."
    echo "$COMPOSE_CONFIG" > ./.piper_internal/last-invalid-compose.yml
    echo "   (saved to ./.piper_internal/last-invalid-compose.yml for inspection)"
    exit 1
fi
echo "✅ Compose config is valid."

echo "⬇️  Pulling images..."
echo "$COMPOSE_CONFIG" | $DOCKER_COMPOSE -f - pull || true

echo "⚙️  Starting Core Engine with Secure Socket Proxy..."
UP_LOG=$(mktemp)
echo "$COMPOSE_CONFIG" | $DOCKER_COMPOSE -f - up -d --remove-orphans 2>&1 | tee "$UP_LOG"
UP_EXIT=${PIPESTATUS[1]}
if [ "$UP_EXIT" -ne 0 ]; then
    if grep -qi "ports are not available\|address already in use\|bind:" "$UP_LOG"; then
        CONFLICT_PORT=$(grep -oE '0\.0\.0\.0:[0-9]+' "$UP_LOG" | head -1 | cut -d: -f2)
        echo ""
        echo "❌ A port needed by this stack is already in use on your host${CONFLICT_PORT:+ (port $CONFLICT_PORT)}."
        echo "   Find what's using it:"
        echo "     Windows (regular terminal, not Git Bash): netstat -ano | findstr :${CONFLICT_PORT:-443}"
        echo "                                                 tasklist /FI \"PID eq <pid-from-above>\""
        echo "     macOS/Linux:                               lsof -i :${CONFLICT_PORT:-443}"
        echo "   Common culprits: IIS/World Wide Web Publishing Service, Skype, a VPN client, or a leftover container."
        echo "   Or just move this stack off the conflicting port — edit .env and set:"
        echo "     NGINX_HTTP_PORT=8080"
        echo "     NGINX_HTTPS_PORT=8443"
        echo "   then rerun this script."
    fi
    rm -f "$UP_LOG"
    exit 1
fi
rm -f "$UP_LOG"

echo "⏳ Waiting for Database connection layer to settle..."
# Recovery after an unclean shutdown (crash, force-kill, host reboot) can take
# well over 60s, especially on Docker Desktop/Windows where volume I/O is
# slower than native Linux. Give it more room, and show what Postgres is
# actually doing instead of just printing dots.
DB_WAIT_TIMEOUT=${DB_WAIT_TIMEOUT:-300}
DB_WAIT_ELAPSED=0
DB_LAST_LOG_CHECK=0
until docker exec piper-db pg_isready -U piper_admin -d piper_data >/dev/null 2>&1; do
    if [ "$DB_WAIT_ELAPSED" -ge "$DB_WAIT_TIMEOUT" ]; then
        echo -e "\n❌ Database did not become ready within ${DB_WAIT_TIMEOUT}s. Recent logs:"
        docker logs --tail 50 piper-db
        echo -e "\nCheck: is the piper-db container running at all? -> docker ps -a | grep piper-db"
        exit 1
    fi
    # Every 20s, show the latest log line so you can see whether it's actively
    # recovering (e.g. "syncing data directory") vs. actually stuck.
    if [ $((DB_WAIT_ELAPSED - DB_LAST_LOG_CHECK)) -ge 20 ]; then
        LAST_LINE=$(docker logs --tail 1 piper-db 2>&1)
        echo -e "\n   [${DB_WAIT_ELAPSED}s] $LAST_LINE"
        DB_LAST_LOG_CHECK=$DB_WAIT_ELAPSED
    else
        echo -n "."
    fi
    sleep 2
    DB_WAIT_ELAPSED=$((DB_WAIT_ELAPSED + 2))
done
echo -e "\n✅ Database Engine is accepting operations!"

# 4b. 🩺 POST-START HEALTH CHECK — verify every service actually stayed up,
# not just the db. Without this, a crash-looping service still gets reported
# as "SUCCESS" below.
echo "🩺 Verifying all core services are running..."
# 🛠️ FIX: "piper-frontend" was in this list, on the same stale belief
# corrected above — the compose file defined below never creates a
# container by that name (12 container_name entries total; see them
# all with `grep container_name:`), so docker inspect on it returns
# "missing" forever. That's not a transient race this loop's retry
# window could ever resolve — it's a permanent, guaranteed failure on
# every single run, in every environment, since the container this was
# waiting for was never going to exist. Removed it here; the fix above
# (dropping it from cleanup too) was the same belief, just harmless
# there instead of fatal.
SERVICES_TO_CHECK="piper-docker-proxy piper-db piper-redis piper-engine-manager piper-engine-controller piper-engine-servers piper-engine-services piper-nginx"
# 🛠️ FIX: this used to be a single instant check right after the DB became
# ready. A service can legitimately restart once on its very first
# connection attempt (even WITH a correct depends_on, since a healthcheck
# passing doesn't guarantee the depended-on service is instantly reachable
# on the network yet) and settle a few seconds later — checking exactly
# once caught services mid-restart-backoff and reported them as failed
# when they'd have come up fine moments later. Retrying for up to 30s
# before declaring an actual failure gives that settling time a chance,
# while still failing fast (not hanging forever) on a genuinely broken
# service.
HEALTH_CHECK_TIMEOUT=30
HEALTH_CHECK_ELAPSED=0
while true; do
    FAILED_SERVICES=""
    for svc in $SERVICES_TO_CHECK; do
        STATE=$(docker inspect -f '{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
        if [ "$STATE" != "running" ]; then
            FAILED_SERVICES="$FAILED_SERVICES $svc($STATE)"
        fi
    done
    if [ -z "$FAILED_SERVICES" ]; then
        break
    fi
    if [ "$HEALTH_CHECK_ELAPSED" -ge "$HEALTH_CHECK_TIMEOUT" ]; then
        echo -e "\n❌ The following services are not running after ${HEALTH_CHECK_TIMEOUT}s:$FAILED_SERVICES"
        echo "   Check logs with: docker logs <container-name>"
        exit 1
    fi
    # 🛠️ FIX: this loop previously printed NOTHING between the initial
    # "Verifying..." line and either success or the 30s-later failure —
    # unlike the DB-wait loop immediately above it, which prints a "."
    # every 2s. A silent 30-second stretch right after a fresh curl|bash
    # install looks indistinguishable from a genuine hang, which is
    # exactly what was reported here even though the loop WAS retrying
    # correctly and would have failed with a clear message at 30s. A
    # dot every retry (3s) makes "still checking" visibly distinct from
    # "frozen" without adding meaningful noise.
    echo -n "."
    sleep 3
    HEALTH_CHECK_ELAPSED=$((HEALTH_CHECK_ELAPSED + 3))
done
echo -e "\n✅ All core services are running."

# 5. HANDSHAKE
echo -e "\n🚀 Running Core Initialization..."
if ! "$INSTALL_DIR/piper" init; then
    echo "❌ 'piper init' failed. Engine containers are up, but initialization did not complete."
    echo "   Check: $INSTALL_DIR/piper init  (rerun manually for full output)"
    exit 1
fi
alias piper="$INSTALL_DIR/piper"

echo -e "\n------------------------------------------------"
echo "✅ SUCCESS: Piper Engine Online & Secured (Bare Mode)"
echo "------------------------------------------------"
echo "🔑 Nginx admin header secret is stored in .env as PIPER_ADMIN_SECRET"
echo "   (send it as the X-Piper-Secret header to reach the proxied app)"