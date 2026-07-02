# API 文档

研策中枢 AlphaScope FastAPI 后端提供 100+ REST 端点(见 `http://localhost:8000/docs` 自动文档)。

启动方式：
```bash
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
# API 文档: http://localhost:8000/docs
```

## 通用响应格式

所有端点返回统一的 `ApiResponse` 结构：

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "message": null
}
```

错误时：
```json
{
  "success": false,
  "data": null,
  "error": "错误信息"
}
```

## 端点列表

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查 |
| GET | `/api/providers/health` | 数据源健康状态 |

### 对话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/conversations` | 创建会话 |
| GET | `/api/conversations` | 列出会话 |
| GET | `/api/conversations/{id}` | 获取会话详情 |
| DELETE | `/api/conversations/{id}` | 删除会话 |

### 聊天与分析

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/stream` | SSE 流式聊天 |
| POST | `/api/analysis/run` | 运行 Agent 分析 |
| POST | `/api/vision/analyze` | 图片/K线分析 |

### 配置查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agents` | Agent 配置列表 |
| GET | `/api/agents/models` | Agent 模型分配表 |
| GET | `/api/teams` | 专家团列表 |
| GET | `/api/teams/{id}` | 专家团详情 |
| GET | `/api/models/providers` | 模型供应商列表 |
| GET | `/api/models/providers/{id}/models` | 供应商模型列表 |
| GET | `/api/modes` | 分析模式列表 |
| GET | `/api/templates` | 研究模板列表 |
| GET | `/api/templates/{id}` | 模板详情 |

### 报告与数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/reports/{id}` | 获取分析报告 |
| GET | `/api/search` | 联网搜索 |
| GET | `/api/costs` | LLM 成本统计 |
| GET | `/api/backtest/stats` | 回测统计 |
| GET | `/api/backtest/agent-accuracy` | Agent 准确率 |
| GET | `/api/backtest/pending` | 待评估决策 |
| GET | `/api/audit` | 审计日志 |
| POST | `/api/files/upload` | 文件上传 |

### 设置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings/providers` | 列出所有 Provider |
| POST | `/api/settings/providers` | 添加/更新 Provider |
| DELETE | `/api/settings/providers/{id}` | 删除 Provider |
| POST | `/api/settings/providers/{id}/test` | 测试连接 |
| GET | `/api/settings/providers/{id}/models` | 列出 Provider 模型 |
| GET | `/api/settings/export` | 导出设置（脱敏） |
| POST | `/api/settings/import` | 导入设置 |

### 报告中心

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/archive` | 报告列表（支持 stock/decision/date/type 筛选） |
| GET | `/api/archive/stats` | 全局统计（总数、买/卖/持分布） |
| GET | `/api/archive/combo-stats` | 模型组合统计 |
| GET | `/api/archive/{path}` | 读取报告 Markdown 全文 |
| DELETE | `/api/archive/{path}` | 删除报告 |

### 任务中心

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 任务列表（支持 status 筛选） |
| GET | `/api/tasks/{id}` | 任务详情 |
| POST | `/api/tasks/{id}/cancel` | 取消任务 |
| POST | `/api/analysis/async` | 异步运行分析（返回 task_id） |

### Agent/专家团管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/manage/agents` | Agent 列表 |
| POST | `/api/manage/agents` | 创建/更新 Agent |
| DELETE | `/api/manage/agents/{id}` | 删除 Agent |
| GET | `/api/manage/teams` | 专家团列表 |
| POST | `/api/manage/teams` | 创建/更新专家团 |
| DELETE | `/api/manage/teams/{id}` | 删除专家团 |

## SSE 流式聊天

`POST /api/chat/stream` 返回 `text/event-stream`：

```
data: {"type": "status", "mode": "deep"}

data: {"type": "content", "chunk": "根据"}

data: {"type": "content", "chunk": "分析..."}

data: {"type": "evidence", "data": [...]}

data: {"type": "agents", "data": {...}}

data: {"type": "done"}
```

### 集成中心 / 插件市场

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/integrations` | 已注册 adapter 列表(vectorBT/OpenBB/Qlib/TradingAgents) |
| GET | `/api/integrations/boundary` | 交易边界(No-Live-Order)概览 |
| GET | `/api/integrations/marketplace` | 插件市场目录(可选 category/installed_only 过滤,给安装指引) |
| GET | `/api/integrations/{name}` | 单 adapter 详情 |
| GET | `/api/integrations/{name}/health` | adapter 健康检查 |
| POST | `/api/integrations/{name}/run` | 运行 adapter 分析(研究语义) |

### 诊断 / MLOps / MCP

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/diagnostics/summary` | 诊断汇总 |
| GET | `/api/diagnostics/tool-calls` | 工具调用日志 |
| GET | `/api/diagnostics/model-calls` | 模型调用日志 |
| GET | `/api/diagnostics/cost-summary` | LLM 成本汇总 |
| GET | `/api/diagnostics/mcp` | MCP server 能力概览 + Claude Desktop 接入配置 |
| GET | `/api/diagnostics/mlops` | MLOps 库就绪概览(mlflow/optuna/evidently 等) |
| GET | `/api/monitor/snapshot` | 系统监控快照(数据源/回测/实验/成本/工具/追踪六路健康聚合) |

## Pydantic Schema

所有请求/响应使用 Pydantic 模型验证，定义在 `backend/schemas/`：

- `backend/schemas/api.py` — API 请求/响应模型
- `backend/schemas/agents.py` — Agent/Team 配置模型
- `backend/schemas/data_source.py` — 数据源模型
- `backend/schemas/evidence.py` — 证据链模型
