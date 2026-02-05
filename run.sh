#!/bin/bash

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "错误: 未找到 .env 文件。请复制 .env.example 到 .env 并设置 GEMINI_API_KEY。"
    echo "  cp .env.example .env"
    exit 1
fi

# 激活虚拟环境并启动服务
source venv/bin/activate

echo "正在启动服务..."
echo "  - 健康检查: http://0.0.0.0:8000/health"
echo "  - 生成接口: POST http://0.0.0.0:8000/generate"

# 多 worker 模式启动
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
