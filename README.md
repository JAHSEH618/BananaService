# Gemini Image Generation Service

[中文](#中文文档) | [English](#english-documentation)

---

## 中文文档

### 简介

这是一个基于 FastAPI 的高并发 Gemini 图像生成 API 中转服务，支持文本和图片输入。

### 项目结构

```
BananaService/
├── main.py              # 主应用入口
├── config.py            # 配置管理 (pydantic-settings)
├── requirements.txt     # Python 依赖
├── .env.example         # 环境变量模板
├── .env                 # 实际环境变量 (gitignore)
├── .gitignore          # Git 忽略配置
├── README.md           # 本文档
│
├── start.sh            # 启动脚本
├── stop.sh             # 停止脚本
├── restart.sh          # 重启脚本
├── run.sh              # 开发模式运行
├── test_request.sh     # API 测试脚本
│
├── venv/               # 虚拟环境 (gitignore)
└── logs/               # 日志目录 (gitignore)
    └── app.log         # 应用日志
```

### 功能特性

- ✅ **文本/图片输入**: 支持纯文本或图片+文本混合输入
- ✅ **高并发**: 异步架构 + 多 Worker 模式
- ✅ **连接池**: httpx 连接复用 (100 连接)
- ✅ **速率限制**: 60 次/分钟
- ✅ **请求超时**: 120 秒自动超时
- ✅ **健康检查**: `/health` 端点
- ✅ **结构化日志**: 完整的请求追踪

### 快速开始

```bash
# 1. 克隆或下载项目
cd BananaService

# 2. 创建虚拟环境 (如果还没有)
python3 -m venv venv

# 3. 安装依赖
venv/bin/pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，设置 GEMINI_API_KEY

# 5. 启动服务
./start.sh
```

### 服务管理

| 命令 | 说明 |
|------|------|
| `./start.sh` | 后台启动服务 (4 Worker) |
| `./stop.sh` | 停止服务 |
| `./restart.sh` | 重启服务 |
| `./run.sh` | 开发模式 (前台运行，支持热重载) |

### Docker 部署

```bash
# 1. 构建镜像
docker build -t banana-service .

# 2. 运行容器
docker run -d --name banana-service -p 8000:8000 --env-file .env banana-service

# 或者使用 Docker Compose
docker-compose up -d
```


### API 接口

#### 健康检查

```bash
curl http://127.0.0.1:8000/health
```

**响应:**
```json
{"status": "healthy", "version": "1.0.0"}
```

#### 生成图像 (纯文本)

```bash
curl -X POST http://127.0.0.1:8000/generate \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "一只穿着宇航服的香蕉"
         }'
```

#### 生成图像 (图片+文本)

```bash
curl -X POST http://127.0.0.1:8000/generate \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "根据这张图片生成一个变体",
           "image_base64": "data:image/jpeg;base64,/9j/4AAQ..."
         }'
```

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `prompt` | string | ✅ | 图像描述文本 |
| `image_base64` | string | ❌ | 输入图片 (base64 编码，支持 data URI) |
| `model` | string | ❌ | 模型名称 (默认: gemini-3-pro-image-preview) |
| `number_of_images` | int | ❌ | 生成数量 (默认: 1) |

**响应示例:**
```json
{
  "images": ["base64_encoded_image_1", "base64_encoded_image_2"],
  "metadata": null
}
```

### 配置项

编辑 `.env` 文件:

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `GEMINI_API_KEY` | - | Gemini API 密钥 (必填) |
| `REQUEST_TIMEOUT_SECONDS` | 120 | 请求超时 (秒) |
| `MAX_CONNECTIONS` | 100 | 最大连接数 |
| `RATE_LIMIT_PER_MINUTE` | 60 | 每分钟请求限制 |
| `WORKERS` | 4 | Worker 数量 |

### 日志

日志文件位于 `logs/app.log`。

---

## English Documentation

### Introduction

A high-concurrency FastAPI-based Gemini image generation API proxy service with text and image input support.

### Project Structure

```
BananaService/
├── main.py              # Main application entry
├── config.py            # Configuration management (pydantic-settings)
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variables template
├── .env                 # Actual environment variables (gitignore)
├── .gitignore          # Git ignore configuration
├── README.md           # This document
│
├── start.sh            # Start script
├── stop.sh             # Stop script
├── restart.sh          # Restart script
├── run.sh              # Development mode run
├── test_request.sh     # API test script
│
├── venv/               # Virtual environment (gitignore)
└── logs/               # Log directory (gitignore)
    └── app.log         # Application log
```

### Features

- ✅ **Text/Image Input**: Support pure text or image+text hybrid input
- ✅ **High Concurrency**: Async architecture + multi-worker mode
- ✅ **Connection Pooling**: httpx connection reuse (100 connections)
- ✅ **Rate Limiting**: 60 requests/minute
- ✅ **Request Timeout**: 120 seconds auto-timeout
- ✅ **Health Check**: `/health` endpoint
- ✅ **Structured Logging**: Complete request tracing

### Quick Start

```bash
# 1. Clone or download project
cd BananaService

# 2. Create virtual environment (if not exists)
python3 -m venv venv

# 3. Install dependencies
venv/bin/pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set GEMINI_API_KEY

# 5. Start service
./start.sh
```

### Service Management

| Command | Description |
|---------|-------------|
| `./start.sh` | Start service in background (4 workers) |
| `./stop.sh` | Stop service |
| `./restart.sh` | Restart service |
| `./run.sh` | Development mode (foreground, hot reload) |

### Docker Deployment

```bash
# 1. Build image
docker build -t banana-service .

# 2. Run container
docker run -d --name banana-service -p 8000:8000 --env-file .env banana-service

# Or use Docker Compose
docker-compose up -d
```


### API Endpoints

#### Health Check

```bash
curl http://127.0.0.1:8000/health
```

**Response:**
```json
{"status": "healthy", "version": "1.0.0"}
```

#### Generate Image (Text Only)

```bash
curl -X POST http://127.0.0.1:8000/generate \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "A banana wearing a spacesuit"
         }'
```

#### Generate Image (Image + Text)

```bash
curl -X POST http://127.0.0.1:8000/generate \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "Generate a variant based on this image",
           "image_base64": "data:image/jpeg;base64,/9j/4AAQ..."
         }'
```

**Request Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | ✅ | Image description text |
| `image_base64` | string | ❌ | Input image (base64 encoded, supports data URI) |
| `model` | string | ❌ | Model name (default: gemini-3-pro-image-preview) |
| `number_of_images` | int | ❌ | Number of images (default: 1) |

**Response Example:**
```json
{
  "images": ["base64_encoded_image_1", "base64_encoded_image_2"],
  "metadata": null
}
```

### Configuration

Edit `.env` file:

| Key | Default | Description |
|-----|---------|-------------|
| `GEMINI_API_KEY` | - | Gemini API key (required) |
| `REQUEST_TIMEOUT_SECONDS` | 120 | Request timeout (seconds) |
| `MAX_CONNECTIONS` | 100 | Max connections |
| `RATE_LIMIT_PER_MINUTE` | 60 | Requests per minute limit |
| `WORKERS` | 4 | Number of workers |

### Logs

Log file is located at `logs/app.log`.

---

## License

MIT
