# 5. 🧹 HARD CLEANUP (Network & Containers)
echo "🧹 Pruning existing system components..."
# Force remove containers first so the network isn't "in use"
docker rm -f piper-db piper-engine-master 2>/dev/null || true

# Identify and kill any worker containers that might be holding the network hostage
WORKERS=$(docker ps -a -q --filter "name=_engine")
if [ -n "$WORKERS" ]; then
    echo "🛑 Stopping active workers..."
    docker rm -f $WORKERS 2>/dev/null || true
fi

# The Magic Fix: Force remove the network by name
echo "🌐 Resetting piper-network..."
docker network rm piper-network 2>/dev/null || true
docker network create piper-network