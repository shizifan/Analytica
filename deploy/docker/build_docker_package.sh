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
echo "[0/6] Preflight checks ..."

if ! command -v docker &>/dev/null; then
    echo "[ERROR] Docker is not installed or not in PATH."
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "[ERROR] Docker daemon is not running."
    exit 1
fi

echo "  Docker OK."

# ── Step 1: Build frontend ───────────────────────────────
echo ""
echo "[1/6] Building frontend ..."
cd "$PROJECT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    echo "  Installing frontend dependencies ..."
    npm install
fi
echo "  Building frontend dist ..."
npm run build
FRONTEND_DIST="$PROJECT_DIR/frontend/dist"
if [ ! -f "$FRONTEND_DIST/index.html" ]; then
    echo "[ERROR] Frontend build failed: index.html not found."
    exit 1
fi
echo "  Frontend built successfully."

# ── Step 2: Build application image ───────────────────────
echo ""
echo "[2/6] Building application image for $PLATFORM ..."
cd "$PROJECT_DIR"
docker buildx build \
    --platform "$PLATFORM" \
    -t analytica:latest \
    --load \
    .
echo "  Image 'analytica:latest' built."

# Reclaim dangling images from previous builds (same tag got reassigned).
docker image prune -f >/dev/null
echo "  Dangling images pruned."

# ── Step 3: Pull MySQL image (optional) ───────────────────
if [ "$SKIP_MYSQL" != "true" ]; then
    echo ""
    echo "[3/6] Pulling MySQL 8.0 image for $PLATFORM ..."
    docker pull --platform "$PLATFORM" mysql:8.0
    echo "  Image 'mysql:8.0' pulled."
else
    echo ""
    echo "[3/6] Skipping MySQL image (already deployed on target)."
fi

# ── Step 4: Save images ───────────────────────────────────
echo ""
echo "[4/6] Saving Docker images ..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/$PACKAGE_NAME/images"

echo "  Saving analytica:latest ..."
docker save analytica:latest | gzip > "$BUILD_DIR/$PACKAGE_NAME/images/analytica-app.tar.gz"

echo "  Saving nginx:alpine ..."
docker pull --platform "$PLATFORM" nginx:alpine
docker save nginx:alpine | gzip > "$BUILD_DIR/$PACKAGE_NAME/images/nginx-alpine.tar.gz"

if [ "$SKIP_MYSQL" != "true" ]; then
    echo "  Saving mysql:8.0 ..."
    docker save mysql:8.0 | gzip > "$BUILD_DIR/$PACKAGE_NAME/images/mysql-8.0.tar.gz"
fi

echo "  Images saved."

# ── Step 5: Assemble deployment package ───────────────────
echo ""
echo "[5/6] Assembling deployment package ..."

# docker-compose.yml
cp "$PROJECT_DIR/docker-compose.yml" "$BUILD_DIR/$PACKAGE_NAME/"

# .env template
cp "$SCRIPT_DIR/env.docker" "$BUILD_DIR/$PACKAGE_NAME/.env"

# Deploy script
cp "$SCRIPT_DIR/deploy_docker.sh" "$BUILD_DIR/$PACKAGE_NAME/deploy.sh"
chmod +x "$BUILD_DIR/$PACKAGE_NAME/deploy.sh"

# nginx config (must be a file, not a directory)
if [ -d "$SCRIPT_DIR/nginx.conf" ]; then
    echo "[ERROR] nginx.conf is a directory, not a file. Please remove it first."
    exit 1
fi
if [ -f "$SCRIPT_DIR/nginx.conf" ]; then
    cp "$SCRIPT_DIR/nginx.conf" "$BUILD_DIR/$PACKAGE_NAME/"
else
    echo "[ERROR] nginx.conf not found at $SCRIPT_DIR/nginx.conf"
    exit 1
fi

# Frontend dist
echo "  Copying frontend dist ..."
cp -r "$FRONTEND_DIST" "$BUILD_DIR/$PACKAGE_NAME/frontend-dist"
# Strip macOS AppleDouble sidecar files (._foo) that `cp`/`tar` would otherwise embed.
find "$BUILD_DIR/$PACKAGE_NAME/frontend-dist" -name '._*' -delete 2>/dev/null || true
# Ensure world-readable so the `nginx` user inside the container can serve them.
chmod -R a+rX "$BUILD_DIR/$PACKAGE_NAME/frontend-dist"

# Deployment guide
if [ -f "$SCRIPT_DIR/README-DEPLOY.md" ]; then
    cp "$SCRIPT_DIR/README-DEPLOY.md" "$BUILD_DIR/$PACKAGE_NAME/"
fi

echo "  Package assembled."

# ── Step 6: Create archive ────────────────────────────────
echo ""
echo "[6/6] Creating archive ..."
cd "$BUILD_DIR"

# 1) 清掉 macOS 扩展属性（com.apple.provenance / com.apple.quarantine 等），
#    否则 bsdtar 会把它们塞进 tar 扩展头，Linux GNU tar 解包会一路 warn。
if command -v xattr &>/dev/null; then
    xattr -cr "$PACKAGE_NAME" 2>/dev/null || true
fi

# 2) 直接尝试用 bsdtar 的 --options 禁用 xattr + mac metadata。
#    bsdtar ≥ 3.x 的 `--help` 输出是精简版，即便不列出这些选项也是支持的，
#    因此不做 `--help` 检测，失败时自动回退到基础 tar。
#    COPYFILE_DISABLE=1 仍作为 AppleDouble (._foo) 兜底。
if ! COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -czf "$OUTPUT" "$PACKAGE_NAME" 2>/dev/null; then
    echo "  [fallback] tar without --no-xattrs/--no-mac-metadata ..."
    COPYFILE_DISABLE=1 tar -czf "$OUTPUT" "$PACKAGE_NAME"
fi

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
echo "    │   └── nginx-alpine.tar.gz"
if [ "$SKIP_MYSQL" != "true" ]; then
echo "    │   └── mysql-8.0.tar.gz"
fi
echo "    ├── docker-compose.yml"
echo "    ├── nginx.conf"
echo "    ├── frontend-dist/"
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
