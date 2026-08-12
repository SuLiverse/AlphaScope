# API Contract Reference

前后端契约文档。所有接口格式以此为准。

> 当前版本以 `pyproject.toml` 为准（撰写时 1.9.x）。

## 1. ApiResponse 格式

所有 REST 端点返回统一结构：

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "message": "..."
}
```

### 成功响应

```json
{
  "success": true,
  "data": { "status": "healthy" },
  "error": null,
  "message": null
}
```

### 错误响应

```json
{
  "success": false,
  "data": null,
  "error": "错误信息"
}
```

## 2. SSE 事件格式

`POST /api/chat/stream` 返回 `text/event-stream`。

事件顺序：`status` → `content*` → `evidence?` → `agents?` → `done`

### status（始终第一个）

```
data: {"type": "status", "mode": "free|standard|deep|expert|vision"}
```

### content（一个或多个，每块最多 20 字符）

```
data: {"type": "content", "chunk": "..."}
```

- `chunk`：字符串，最大 20 字符
- 拼接所有 content chunk 即完整回复文本

### evidence（条件发送：仅当非空时）

```
data: {"type": "evidence", "data": [...]}
```

- `data`：证据对象数组

### agents（条件发送：仅当非空时）

```
data: {"type": "agents", "data": {...}}
```

- `data`：以 agent 名称为 key 的对象

### done（始终最后一个）

```
data: {"type": "done"}
```

### 错误行为

orchestrator 异常时，端点返回 JSON 错误（非 SSE error event）：

```json
{
  "success": false,
  "error": "内部服务器错误"
}
```

## 3. 文件上传格式

`POST /api/files/upload`（multipart/form-data）

成功响应：

```json
{
  "success": true,
  "data": {
    "filename": "test.png",
    "size": 1234,
    "path": "uploads/{md5_hash}_test.png",
    "message": "上传成功"
  }
}
```

支持格式：`.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.pdf` `.csv` `.xlsx`
大小限制：20 MB

## 4. 错误格式

### HTTP 400（校验失败）

```json
{"success": false, "error": "不支持的文件格式: .exe"}
```

### HTTP 404（资源不存在）

```json
{"success": false, "error": "对话不存在"}
```

### HTTP 500（内部错误）

```json
{"success": false, "error": "内部服务器错误"}
```

## 5. 降级行为

| 场景 | 行为 |
|------|------|
| 无 ChromaDB | 应用正常启动，向量搜索抛 RuntimeError |
| 无 API Key | 应用正常启动，create_client 抛 "供应商未配置完整" |
| 无 Tavily Key | 搜索端点返回不可用提示 |
| 网络失败 | 返回明确错误信息 |
