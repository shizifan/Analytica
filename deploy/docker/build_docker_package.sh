#!/bin/bash
# ============================================================
# Analytica - Build Docker Offline Deployment Package
# Run this on the development machine (with network access)
#
# Usage:
#   bash build_docker_package.sh              # App only (default)
#   SKIP_MYSQL=false bash build_docker_package.sh  # Include MySQL
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PACKAGE_NAME="analytica-docker-${TIMESTAMP}"
BUILD_DIR="$PROJECT_DIR/build_docker"
OUTPUT="$PROJECT_DIR/${PACKAGE_NAME}.tar.gz"
PLATFORM="linux/arm64"
SKIP_MYSQL="${SKIP_MYSQL:-true}"

echo "============================================"
echo "  Analytica Docker Offline Package Builder"
echo "  Platform: $PLATFORM"
echo "  Skip MySQL: $SKIP_MYSQL"
echo "============================================"

# ── Preflight checks ──────────────────────────────────────
echo ""
echo "[0/5] Preflight checks ..."

if ! command -v docker &>/dev/null; then
    echo "[ERROR] Docker is not installed or not in PATH."
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "[ERROR] Docker daemon is not running."
    exit 1
fi

echo "  Docker OK."

# ── Step 1: Build application image ───────────────────────
echo ""
echo "[1/5] Building application image for $PLATFORM ..."
cd "$PROJECT_DIR"
docker buildx build \
    --platform "$PLATFORM" \
    -t analytica:latest \
    --load \
    .
echo "  Image 'analytica:latest' built."

# ── Step 2: Pull MySQL image (optional) ───────────────────
if [ "$SKIP_MYSQL" != "true" ]; then
    echo ""
    echo "[2/5] Pulling MySQL 8.0 image for $PLATFORM ..."
    docker pull --platform "$PLATFORM" mysql:8.0
    echo "  Image 'mysql:8.0' pulled."
else
    echo ""
    echo "[2/5] Skipping MySQL image (already deployed on target)."
fi

# ── Step 3: Save images ───────────────────────────────────
echo ""
echo "[3/5] Saving Docker images ..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/$PACKAGE_NAME/images"

echo "  Saving analytica:latest ..."
docker save analytica:latest | gzip > "$BUILD_DIR/$PACKAGE_NAME/images/analytica-app.tar.gz"

if [ "$SKIP_MYSQL" != "true" ]; then
    echo "  Saving mysql:8.0 ..."
    docker save mysql:8.0 | gzip > "$BUILD_DIR/$PACKAGE_NAME/images/mysql-8.0.tar.gz"
fi

echo "  Images saved."

# ── Step 4: Assemble deployment package ───────────────────
echo ""
echo "[4/5] Assembling deployment package ..."

# docker-compose.yml
cp "$PROJECT_DIR/docker-compose.yml" "$BUILD_DIR/$PACKAGE_NAME/"

# .env template
cp "$SCRIPT_DIR/env.docker" "$BUILD_DIR/$PACKAGE_NAME/.env"

# Deploy script
cp "$SCRIPT_DIR/deploy_docker.sh" "$BUILD_DIR/$PACKAGE_NAME/deploy.sh"
chmod +x "$BUILD_DIR/$PACKAGE_NAME/deploy.sh"

# Deployment guide
if [ -f "$SCRIPT_DIR/README-DEPLOY.md" ]; then
    cp "$SCRIPT_DIR/README-DEPLOY.md" "$BUILD_DIR/$PACKAGE_NAME/"
fi

echo "  Package assembled."

# ── Step 5: Create archive ────────────────────────────────
echo ""
echo "[5/5] Creating archive ..."
cd "$BUILD_DIR"
tar czf "$OUTPUT" "$PACKAGE_NAME"

# Cleanup build dir
rm -rf "$BUILD_DIR"

SIZE=$(du -sh "$OUTPUT" | cut -f1)

echo ""
echo "============================================"
echo "  Package created successfully!"
echo ""
echo "  File: $OUTPUT"
echo "  Size: $SIZE"
echo ""
echo "  Package contents:"
echo "    ${PACKAGE_NAME}/"
echo "    ├── images/"
echo "    │   ├── analytica-app.tar.gz"
if [ "$SKIP_MYSQL" != "true" ]; then
echo "    │   └── mysql-8.0.tar.gz"
fi
echo "    ├── docker-compose.yml"
echo "    ├── .env"
echo "    ├── deploy.sh"
echo "    └── README-DEPLOY.md"
echo ""
echo "  Deployment steps on Kylin Server V10:"
echo "    1. scp ${PACKAGE_NAME}.tar.gz user@server:/opt/"
echo "    2. ssh user@server"
echo "    3. cd /opt && tar xzf ${PACKAGE_NAME}.tar.gz"
echo "    4. cd ${PACKAGE_NAME}"
echo "    5. vi .env   # Review and adjust settings"
echo "    6. bash deploy.sh"
echo "============================================"
