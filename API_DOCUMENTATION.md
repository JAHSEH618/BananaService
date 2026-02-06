# Banana Service API 文档

本文档详细描述了 Banana Service 提供的 API 接口，包括输入、输出及可能的错误代码。

## 1. 概览

- **基础 URL**: `http://<host>:<port>` (默认端口: 8000)
- **认证方式**: 所有受保护的接口需要在 HTTP 请求头中携带 API Key。
- **内容类型**: `application/json`

## 2. 认证 (Authentication)

调用核心功能接口（如生成图片）时，必须在请求头中包含 `X-API-Key`。

| Header 字段 | 说明 | 示例 |
| :--- | :--- | :--- |
| `X-API-Key` | 服务端配置的访问密钥 (`SERVICE_API_KEY`) | `X-API-Key: xiaozhi-secret-key` |

---

## 3. 接口详情

### 3.1 健康检查 (Health Check)

用于检查服务运行状态及版本信息。常用于负载均衡器或容器探活。

- **Endpoint**: `/health`
- **Method**: `GET`
- **Auth Required**: 否

#### 响应 (Response)

```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `status` | string | 服务状态，正常返回 "healthy" |
| `version` | string | 当前服务版本号 |

---

### 3.2 生成图像 (Generate Image)

调用 Gemini 模型生成图像。支持纯文本提示词，或文本+参考图（图生图）。

- **Endpoint**: `/generate`
- **Method**: `POST`
- **Auth Required**: 是 (`X-API-Key`)
- **Rate Limit**: 默认 60 请求/分钟

#### 请求参数 (Request Body)

Content-Type: `application/json`

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `prompt` | string | **是** | - | 图像生成的描述文本。 |
| `image_base64` | string | 否 | null | 参考图片的 Base64 编码字符串。支持带前缀 (e.g., `data:image/jpeg;base64,...`) 或纯 Base64 串。 |
| `model` | string | 否 | "gemini-3-pro-image-preview" | 使用的 Gemini 模型名称。 |
| `aspect_ratio` | string | 否 | null | 图片宽高比 (如 "16:9", "1:1")。*注：当前代码逻辑中主要是透传给模型，具体支持取决于模型版本。* |
| `number_of_images` | int | 否 | 1 | 希望生成的图片数量。 |

#### 请求示例

**仅文本:**

```json
{
  "prompt": "一只在太空漫步的赛博朋克风格猫咪",
  "number_of_images": 1
}
```

**文本 + 参考图:**

```json
{
  "prompt": "基于这张草图生成的真实风格建筑渲染图",
  "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "model": "gemini-3-pro-image-preview"
}
```

#### 成功响应 (Success Response)

HTTP Status Code: `200 OK`

```json
{
  "images": [
    "iVBORw0KGgoAAAANSUhEUgAA..." 
  ],
  "metadata": null
}
```

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `images` | List[string] | 生成图片的 Base64 编码列表。 |
| `metadata` | dict \| null | 预留的元数据字段，目前返回 null。 |

---

## 4. 错误处理 (Error Handling)

当请求失败时，服务将返回标准的 HTTP 错误码及 JSON 格式的错误详情。

**错误响应格式:**

```json
{
  "detail": "具体的错误描述信息"
}
```

### 常见错误码

| HTTP 状态码 | 含义 | 可能原因 |
| :--- | :--- | :--- |
| `401 Unauthorized` | 未授权 | 请求头缺少 `X-API-Key` 或 Key 无效。 |
| `429 Too Many Requests` | 请求过多 | 超过了速率限制 (默认 60次/分钟)。 |
| `500 Internal Server Error` | 服务器内部错误 | Gemini API 调用失败、Base64 解码错误、未生成图片或其他未捕获异常。 |
| `504 Gateway Timeout` | 超时 | 生成过程超过了设定的 `REQUEST_TIMEOUT_SECONDS` (默认 120秒)。 |

### 错误响应示例 (504 Timeout)

```json
{
  "detail": "请求超时"
}
```

### 错误响应示例 (401 Unauthorized)

```json
{
  "detail": "无效的 API Key"
}
```
