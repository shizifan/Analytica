#!/bin/bash
# ============================================================
# Analytica Docker Entrypoint
# 1. Wait for MySQL to be ready
# 2. Run Alembic migrations
# 3. Start uvicorn server
# ============================================================
set -e

MAX_RETRIES=30
RETRY_INTERVAL=2

echo "============================================"
echo "  Analytica Docker Entrypoint"
echo "============================================"

# ── Step 1: Wait for MySQL ────────────────────────────────
echo "[1/3] Waiting for MySQL at db:3306 ..."
for i in $(seq 1 $MAX_RETRIES); do
    if python -c "import socket; s=socket.create_connection(('db',3306),timeout=2); s.close()" 2>/dev/null; then
        echo "  MySQL is reachable."
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "[ERROR] MySQL not reachable after $((MAX_RETRIES * RETRY_INTERVAL))s. Exiting."
        exit 1
    fi
    echo "  attempt $i/$MAX_RETRIES ..."
    sleep $RETRY_INTERVAL
done

# Extra wait for MySQL to be fully ready for queries
sleep 3

# ── Step 2: Run Alembic migrations ────────────────────────
echo "[2/3] Running database migrations ..."
alembic upgrade head
echo "  Migrations complete."

# ── Step 3: Start uvicorn ─────────────────────────────────
WORKERS="${WORKERS:-1}"
LOG_LEVEL="${LOG_LEVEL:-info}"

echo "[3/3] Starting Analytica server ..."
echo "  Workers: $WORKERS"
echo "  Log Level: $LOG_LEVEL"
echo "============================================"

exec python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --log-level "$LOG_LEVEL"
