#!/bin/bash
# ============================================================
# Analytica - Docker Offline Deployment Script
# Run this on the target server (Kylin Server V10, aarch64)
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  Analytica Docker Deployment"
echo "  Target: Kylin Server V10 (aarch64)"
echo "============================================"

# ── Preflight checks ──────────────────────────────────────
echo ""
echo "[0/5] Preflight checks ..."

if ! command -v docker &>/dev/null; then
    echo "[ERROR] Docker is not installed."
    echo "  Please install Docker Engine first:"
    echo "    https://docs.docker.com/engine/install/"
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "[ERROR] Docker daemon is not running."
    echo "  Try: sudo systemctl start docker"
    exit 1
fi

# Check docker compose (v2 plugin or standalone)
COMPOSE_CMD=""
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo "[ERROR] Docker Compose is not installed."
    echo "  Please install Docker Compose v2:"
    echo "    https://docs.docker.com/compose/install/"
    exit 1
fi

echo "  Docker: OK"
echo "  Compose: $COMPOSE_CMD"

# ── Step 1: Load Docker images ────────────────────────────
echo ""
echo "[1/5] Loading Docker images ..."

if [ -f "$SCRIPT_DIR/images/analytica-app.tar.gz" ]; then
    echo "  Loading analytica:latest ..."
    docker load -i "$SCRIPT_DIR/images/analytica-app.tar.gz"
else
    echo "[ERROR] Image file not found: images/analytica-app.tar.gz"
    exit 1
fi

if [ -f "$SCRIPT_DIR/images/mysql-8.0.tar.gz" ]; then
    echo "  Loading mysql:8.0 ..."
    docker load -i "$SCRIPT_DIR/images/mysql-8.0.tar.gz"
else
    echo "  Skipping MySQL image (not in package, assuming already loaded)."
fi

if [ -f "$SCRIPT_DIR/images/nginx-alpine.tar.gz" ]; then
    echo "  Loading nginx:alpine ..."
    docker load -i "$SCRIPT_DIR/images/nginx-alpine.tar.gz"
else
    echo "[ERROR] Image file not found: images/nginx-alpine.tar.gz"
    exit 1
fi

echo "  Images loaded."

# ── Step 2: Copy frontend dist ────────────────────────────
echo ""
echo "[2/5] Copying frontend dist ..."

if [ -d "$SCRIPT_DIR/frontend-dist" ]; then
    mkdir -p "$SCRIPT_DIR/frontend"
    rm -rf "$SCRIPT_DIR/frontend/dist"
    # Use trailing slash to copy contents, not the directory itself
    cp -r "$SCRIPT_DIR/frontend-dist/" "$SCRIPT_DIR/frontend/dist/"
    # Strip macOS AppleDouble (._foo) files that slipped into legacy packages.
    find "$SCRIPT_DIR/frontend/dist" -name '._*' -delete 2>/dev/null || true
    # Nginx worker runs as the `nginx` user inside the container; ensure world-readable.
    chmod -R a+rX "$SCRIPT_DIR/frontend/dist"
    echo "  Frontend dist copied to frontend/dist/."

    # Verify the copy was successful
    if [ -f "$SCRIPT_DIR/frontend/dist/index.html" ]; then
        echo "  Verification: index.html found."
    else
        echo "[ERROR] index.html not found after copy!"
        echo "  Contents of frontend-dist:"
        ls -la "$SCRIPT_DIR/frontend-dist/"
        echo "  Contents of frontend/"
        ls -la "$SCRIPT_DIR/frontend/"
        exit 1
    fi
else
    echo "[WARN] frontend-dist not found in package, skipping."
fi

# Verify nginx.conf is a file (not a directory)
if [ -d "$SCRIPT_DIR/nginx.conf" ]; then
    echo "[ERROR] nginx.conf is a directory. Please remove it first:"
    echo "  rm -rf \"$SCRIPT_DIR/nginx.conf\""
    exit 1
fi
if [ ! -f "$SCRIPT_DIR/nginx.conf" ]; then
    echo "[ERROR] nginx.conf not found."
    exit 1
fi

# ── Step 3: Check .env configuration ──────────────────────
echo ""
echo "[3/5] Checking configuration ..."

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "[ERROR] .env file not found."
    echo "  Please create .env from the template."
    exit 1
fi

echo "  .env found. Please ensure the following are correctly set:"
echo "    - MYSQL_ROOT_PASSWORD"
echo "    - QWEN_API_KEY"
echo "    - PROD_API_BASE"
echo ""
read -p "  Press Enter to continue (or Ctrl+C to abort and edit .env) ..."

# ── Step 4: Start services ────────────────────────────────
echo ""
echo "[4/5] Starting services ..."
cd "$SCRIPT_DIR"

# Create reports directory if needed
mkdir -p reports

$COMPOSE_CMD up -d

echo "  Services starting..."

# ── Step 5: Wait for health check ─────────────────────────
echo ""
echo "[5/5] Waiting for application to be ready ..."

MAX_WAIT=120
INTERVAL=5
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost:${ANALYTICA_PORT:-8000}/health >/dev/null 2>&1; then
        echo ""
        echo "============================================"
        echo "  Analytica is running!"
        echo ""
        echo "  Backend API:  http://localhost:${ANALYTICA_PORT:-8000}"
        echo "  Health:       http://localhost:${ANALYTICA_PORT:-8000}/health"
        echo "  Frontend:     http://localhost:${FRONTEND_PORT:-3000}"
        echo ""
        echo "  Useful commands:"
        echo "    $COMPOSE_CMD logs -f app       # View app logs"
        echo "    $COMPOSE_CMD logs -f db        # View MySQL logs"
        echo "    $COMPOSE_CMD logs -f frontend  # View nginx logs"
        echo "    $COMPOSE_CMD ps                 # Service status"
        echo "    $COMPOSE_CMD down              # Stop services"
        echo "    $COMPOSE_CMD down -v           # Stop & remove data"
        echo "============================================"
        exit 0
    fi
    echo "  Waiting... ($ELAPSED/${MAX_WAIT}s)"
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

echo ""
echo "[WARN] Application did not become healthy within ${MAX_WAIT}s."
echo "  Check logs: $COMPOSE_CMD logs -f app"
echo "  Services may still be starting up."
$COMPOSE_CMD ps
