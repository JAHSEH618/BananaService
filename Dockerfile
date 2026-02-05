# 使用官方 Python 3.12 轻量级镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
# 防止 Python 生成 .pyc 文件
ENV PYTHONDONTWRITEBYTECODE=1
# 确保 Python 输出直接打印到控制台
ENV PYTHONUNBUFFERED=1

# 安装系统依赖 (如果有需要，例如构建工具)
# RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令 (使用 shell 形式以支持变量扩展，但 exec 形式更好，这里直接用 CMD)
# 生产环境建议使用 gunicorn 管理 uvicorn，或者直接使用 uvicorn workers
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
