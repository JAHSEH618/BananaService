#!/bin/bash
# 停止脚本 / Stop Script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f .pid ]; then
    echo "⚠️  未找到 PID 文件，服务可能未运行 / PID file not found, service may not be running"
    # 尝试通过端口查找并杀死 / Try to find and kill by port
    PID=$(lsof -ti:8000)
    if [ -n "$PID" ]; then
        echo "🔍 通过端口找到进程: $PID / Found process by port: $PID"
        kill -TERM $PID 2>/dev/null
        echo "✅ 已发送停止信号 / Stop signal sent"
    else
        echo "❌ 端口 8000 上无运行的服务 / No service running on port 8000"
    fi
    exit 0
fi

PID=$(cat .pid)

if ps -p $PID > /dev/null 2>&1; then
    echo "🛑 正在停止服务 (PID: $PID)... / Stopping service..."
    kill -TERM $PID
    
    # 等待进程结束 / Wait for process to end
    for i in {1..10}; do
        if ! ps -p $PID > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    
    # 如果仍在运行，强制杀死 / Force kill if still running
    if ps -p $PID > /dev/null 2>&1; then
        echo "⚠️  进程未响应，强制终止... / Process not responding, force killing..."
        kill -9 $PID
    fi
    
    rm -f .pid
    echo "✅ 服务已停止 / Service stopped"
else
    echo "⚠️  进程 $PID 未运行 / Process $PID not running"
    rm -f .pid
fi
