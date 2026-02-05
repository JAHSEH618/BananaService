#!/bin/bash
# 启动脚本 / Start Script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检查 .env 文件 / Check .env file
if [ ! -f .env ]; then
    echo "❌ 错误: 未找到 .env 文件 / Error: .env file not found"
    echo "   请运行: cp .env.example .env 并设置 GEMINI_API_KEY"
    echo "   Please run: cp .env.example .env and set GEMINI_API_KEY"
    exit 1
fi

# 检查是否已运行 / Check if already running
if [ -f .pid ]; then
    PID=$(cat .pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "⚠️  服务已在运行 (PID: $PID) / Service already running"
        echo "   使用 ./stop.sh 停止 / Use ./stop.sh to stop"
        exit 1
    fi
fi

# 激活虚拟环境 / Activate virtual environment
source venv/bin/activate

echo "🚀 正在启动服务... / Starting service..."
echo "   - 健康检查 / Health Check: http://0.0.0.0:8000/health"
echo "   - 生成接口 / Generate API: POST http://0.0.0.0:8000/generate"

# 后台启动并记录 PID / Start in background and record PID
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 > logs/app.log 2>&1 &
echo $! > .pid

echo "✅ 服务已启动 (PID: $(cat .pid)) / Service started"
echo "   日志文件 / Log file: logs/app.log"
