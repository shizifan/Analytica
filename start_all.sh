#!/bin/bash
# Analytica 全量服务启动脚本

set -e

echo "=========================================="
echo "  Analytica 全量服务启动"
echo "=========================================="

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${CYAN}[启动]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[完成]${NC} $1"
}

# 启动函数
start_mock_server() {
    print_step "启动 Mock API Server (端口 18080)..."
    cd "$PROJECT_ROOT"
    uv run python -m mock_server.mock_server_all --port 18080 --host 0.0.0.0 &
    echo $! > /tmp/analytica_mock_server.pid
    print_success "Mock API Server 已启动 (PID: $(cat /tmp/analytica_mock_server.pid))"
}

start_backend() {
    print_step "启动 FastAPI 后端 (端口 8000)..."
    cd "$PROJECT_ROOT"
    uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
    echo $! > /tmp/analytica_backend.pid
    print_success "FastAPI 后端已启动 (PID: $(cat /tmp/analytica_backend.pid))"
}

start_frontend() {
    print_step "启动 Vite 前端 (端口 5173)..."
    cd "$PROJECT_ROOT/frontend"
    npm run dev &
    echo $! > /tmp/analytica_frontend.pid
    print_success "Vite 前端已启动 (PID: $(cat /tmp/analytica_frontend.pid))"
}

# 停止函数
stop_all() {
    echo ""
    echo -e "${YELLOW}[停止]${NC} 停止所有服务..."

    for pid_file in /tmp/analytica_mock_server.pid /tmp/analytica_backend.pid /tmp/analytica_frontend.pid; do
        if [ -f "$pid_file" ]; then
            PID=$(cat "$pid_file")
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID" 2>/dev/null || true
                echo "  - 已停止 PID: $PID"
            fi
            rm -f "$pid_file"
        fi
    done

    echo -e "${GREEN}[完成]${NC} 所有服务已停止"
}

# 状态函数
status() {
    echo ""
    echo "服务状态:"
    echo "----------------------------------------"

    check_service "Mock API Server (18080)" /tmp/analytica_mock_server.pid "http://localhost:18080/docs"
    check_service "FastAPI 后端 (8000)" /tmp/analytica_backend.pid "http://localhost:8000/health"
    check_service "Vite 前端 (5173)" /tmp/analytica_frontend.pid "http://localhost:5173"

    echo "----------------------------------------"
}

check_service() {
    local name=$1
    local pid_file=$2
    local url=$3

    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if kill -0 "$PID" 2>/dev/null; then
            echo -e "  ${GREEN}●${NC} $name - 运行中 (PID: $PID)"
        else
            echo -e "  ${YELLOW}○${NC} $name - 已停止 (PID文件残留)"
        fi
    else
        echo -e "  ○ $name - 未启动"
    fi
}

# 帮助信息
usage() {
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  start     启动全部服务 (默认)"
    echo "  stop      停止全部服务"
    echo "  status    查看服务状态"
    echo "  restart   重启全部服务"
    echo "  help      显示帮助信息"
    echo ""
    echo "服务列表:"
    echo "  - Mock API Server  : http://localhost:18080"
    echo "  - FastAPI 后端     : http://localhost:8000"
    echo "  - Vite 前端        : http://localhost:5173"
}

# 主逻辑
case "${1:-start}" in
    start)
        echo ""
        start_mock_server
        sleep 1
        start_backend
        sleep 1
        start_frontend
        echo ""
        echo "=========================================="
        echo -e "  ${GREEN}全部服务已启动！${NC}"
        echo "=========================================="
        echo ""
        echo "访问地址:"
        echo "  - Mock API : http://localhost:18080/docs"
        echo "  - 后端 API : http://localhost:8000"
        echo "  - 前端页面 : http://localhost:5173"
        echo ""
        echo "停止服务: $0 stop"
        echo ""
        ;;

    stop)
        stop_all
        ;;

    status)
        status
        ;;

    restart)
        stop_all
        sleep 2
        $0 start
        ;;

    help|--help|-h)
        usage
        ;;

    *)
        echo "未知命令: $1"
        usage
        exit 1
        ;;
esac
