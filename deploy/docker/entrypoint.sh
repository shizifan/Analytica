#!/bin/bash
# ============================================================
# Analytica Docker Entrypoint
# 1. Wait for MySQL to be query-ready (SELECT 1, not just TCP ping)
# 2. Run Alembic migrations (with retry)
# 3. Seed reference data (employees + admin registries)
# 4. Start uvicorn server
# ============================================================
set -e

MAX_DB_WAIT=60           # 60 * 2s = 120s 上限，首次 initdb 也够了
DB_POLL_INTERVAL=2
ALEMBIC_RETRIES=5
ALEMBIC_RETRY_DELAY=3

echo "============================================"
echo "  Analytica Docker Entrypoint"
echo "============================================"

# ── Step 1: Wait for MySQL to be QUERY-ready ───────────────
# P1 修复：TCP 端口早于 grant tables 准备好，仅 socket ping 会让后续
# alembic 在"端口通但 DB 未就绪"的窗口里翻车。这里改用真实 SELECT 1
# 复用 backend.database 的连接字符串，确保与应用配置完全一致。
echo "[1/4] Waiting for MySQL to accept SELECT 1 ..."
for i in $(seq 1 $MAX_DB_WAIT); do
    if python - <<'PY' 2>/dev/null
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL_SYNC")
if not url:
    print("DATABASE_URL_SYNC not set", file=sys.stderr)
    sys.exit(2)
engine = create_engine(url, connect_args={"connect_timeout": 3})
with engine.connect() as conn:
    conn.execute(text("SELECT 1")).scalar()
PY
    then
        echo "  MySQL is query-ready."
        break
    fi
    if [ "$i" -eq "$MAX_DB_WAIT" ]; then
        echo "[ERROR] MySQL not query-ready after $((MAX_DB_WAIT * DB_POLL_INTERVAL))s. Exiting."
        exit 1
    fi
    echo "  attempt $i/$MAX_DB_WAIT ..."
    sleep $DB_POLL_INTERVAL
done

# ── Step 2: Run Alembic migrations (with retry) ────────────
# P2 修复：upgrade 可能遇到瞬时连接被 reset / 锁等待，单次失败直接
# 让容器 exit 很浪费 compose 的 health-check 时间。加 5 次重试，
# 彻底失败才退出。
echo "[2/4] Running database migrations ..."
for i in $(seq 1 $ALEMBIC_RETRIES); do
    if alembic upgrade head; then
        echo "  Migrations complete."
        break
    fi
    if [ "$i" -eq "$ALEMBIC_RETRIES" ]; then
        echo "[ERROR] alembic upgrade failed after $ALEMBIC_RETRIES retries. Exiting."
        exit 1
    fi
    echo "  alembic attempt $i/$ALEMBIC_RETRIES failed — retrying in ${ALEMBIC_RETRY_DELAY}s ..."
    sleep $ALEMBIC_RETRY_DELAY
done

# ── Step 3: Seed reference data (idempotent) ───────────────
# P3 修复：admin 表（api_endpoints / skills / domains）原本没 seed，
# 导致管理后台空着；员工 seed 也合并到这一步。两个脚本都是幂等的。
echo "[3/4] Seeding reference data ..."

# 3a — Employees (YAML → employees + employee_versions)
if [ "${FF_EMPLOYEE_SOURCE:-db}" = "db" ]; then
    echo "  [3a] Seeding employees from YAML ..."
    if python -m migrations.scripts.seed_employees_from_yaml; then
        echo "        Employees seed OK."
    else
        echo "  [WARN] Employee seed failed — backend会在 lifespan 里回退 YAML，继续启动。"
    fi
else
    echo "  [3a] Skipping employee seed (FF_EMPLOYEE_SOURCE=${FF_EMPLOYEE_SOURCE})."
fi

# 3b — Admin registries (api_registry / SkillRegistry / DOMAIN_INDEX → DB)
echo "  [3b] Seeding admin registries (api_endpoints / skills / domains) ..."
if python -m migrations.scripts.seed_admin_tables; then
    echo "        Admin registries seed OK."
else
    echo "  [WARN] Admin registry seed failed — 管理后台数据可能不完整，继续启动。"
fi

# ── Step 4: Start uvicorn ─────────────────────────────────
WORKERS="${WORKERS:-1}"
LOG_LEVEL="${LOG_LEVEL:-info}"

echo "[4/4] Starting Analytica server ..."
echo "  Workers: $WORKERS"
echo "  Log Level: $LOG_LEVEL"
echo "============================================"

exec python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --log-level "$LOG_LEVEL"
