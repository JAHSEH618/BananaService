#!/bin/bash
# 重启脚本 / Restart Script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔄 正在重启服务... / Restarting service..."

# 停止服务 / Stop service
./stop.sh

# 等待端口释放 / Wait for port to be released
sleep 2

# 启动服务 / Start service
./start.sh
