# Gemini Image Generation Service

[中文](#中文文档) | [English](#english-documentation)

---

## 中文文档

### 简介

这是一个基于 FastAPI 的高并发 Gemini 图像生成 API 中转服务。

### 功能特性

- ✅ **高并发**: 异步架构 + 多 Worker 模式
- ✅ **连接池**: httpx 连接复用 (100 连接)
- ✅ **速率限制**: 60 次/分钟
- ✅ **请求超时**: 120 秒自动超时
- ✅ **健康检查**: `/health` 端点
- ✅ **结构化日志**: 完整的请求追踪

### 快速开始

```bash
# 1. 创建虚拟环境 (如果还没有)
python3 -m venv venv

# 2. 安装依赖
venv/bin/pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，设置 GEMINI_API_KEY

# 4. 启动服务
./start.sh
```

### 服务管理

| 命令 | 说明 |
|------|------|
| `./start.sh` | 后台启动服务 (4 Worker) |
| `./stop.sh` | 停止服务 |
| `./restart.sh` | 重启服务 |

### API 接口

#### 健康检查

```bash
curl http://127.0.0.1:8000/health
```

#### 生成图像

```bash
curl -X POST http://127.0.0.1:8000/generate \
     -H "Content-Type: application/json" \
     -d '{"prompt": "一只穿着宇航服的香蕉"}'
```

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `prompt` | string | ✅ | 图像描述 |
| `model` | string | ❌ | 模型名称 (默认: gemini-3-pro-image-preview) |
| `number_of_images` | int | ❌ | 生成数量 (默认: 1) |

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

A high-concurrency FastAPI-based Gemini image generation API proxy service.

### Features

- ✅ **High Concurrency**: Async architecture + multi-worker mode
- ✅ **Connection Pooling**: httpx connection reuse (100 connections)
- ✅ **Rate Limiting**: 60 requests/minute
- ✅ **Request Timeout**: 120 seconds auto-timeout
- ✅ **Health Check**: `/health` endpoint
- ✅ **Structured Logging**: Complete request tracing

### Quick Start

```bash
# 1. Create virtual environment (if not exists)
python3 -m venv venv

# 2. Install dependencies
venv/bin/pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and set GEMINI_API_KEY

# 4. Start service
./start.sh
```

### Service Management

| Command | Description |
|---------|-------------|
| `./start.sh` | Start service in background (4 workers) |
| `./stop.sh` | Stop service |
| `./restart.sh` | Restart service |

### API Endpoints

#### Health Check

```bash
curl http://127.0.0.1:8000/health
```

#### Generate Image

```bash
curl -X POST http://127.0.0.1:8000/generate \
     -H "Content-Type: application/json" \
     -d '{"prompt": "A banana wearing a spacesuit"}'
```

**Request Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | ✅ | Image description |
| `model` | string | ❌ | Model name (default: gemini-3-pro-image-preview) |
| `number_of_images` | int | ❌ | Number of images (default: 1) |

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
