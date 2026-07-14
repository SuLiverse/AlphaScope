# 安全文档 (v1.9.52+)

> 本文描述 **当前已实现** 的安全边界。v1.6 时代「CORS 全开 + 无 Auth」的表述已作废。

## 1. 本地 API 鉴权

| 项 | 行为 |
|----|------|
| Token | 启动时 `ensure_local_api_token()` 生成/复用 `ALPHASCOPE_LOCAL_API_TOKEN` |
| Header | `X-AlphaScope-Local-Token`（优先） |
| Query | `local_token=` 仅兼容 SSE/浏览器导航下载 |
| 公开路径 | `/`、`/health`、`/docs`、`/redoc`、`/openapi.json` |
| 关闭鉴权 | 仅测试: `ALPHASCOPE_ALLOW_OPEN_API=1`（勿用于日常桌面） |

前端通过 `runtime-config.js` / `VITE_LOCAL_API_TOKEN` 注入，**不**把第三方 Provider Key 放进前端。

## 2. CORS

| 模式 | 条件 |
|------|------|
| 默认 | 仅匹配 `localhost` / `127.0.0.1` / `[::1]` 的 origin regex |
| 显式白名单 | `ALPHASCOPE_CORS_ORIGINS=https://app.example.com,...` 时允许 credentials |
| 全开放 | **仅** `ALPHASCOPE_ALLOW_ALL_CORS=1`（开发用，不推荐） |

## 3. API Key 加密 (Key Vault)

- 默认 **AES-GCM**（`cryptography`）
- 必须设置 `AI_FINANCE_MASTER_KEY`；launcher 首启自动生成
- 弱 XOR / 固定 dev key **仅当** `AI_FINANCE_ALLOW_DEV_KEY_FALLBACK=1`
- 列表接口不回显 plaintext `api_key`；日志脱敏

## 4. SSRF 防护

- LLM `base_url`: `validate_custom_base_url()` 解析 DNS 并拒绝私网/本机
- 本机代理/Ollama: 显式 `ALLOW_LOCAL_LLM_BASE_URL=1`
- 通用 HTTP 拉数: `url_guard.validate_public_http_url`

## 5. 输入与合规

- Prompt / 股票数据清洗（零宽字符、长度限制）
- 金融禁用词替换 + 免责声明注入
- 上传白名单与大小上限
- 报告质量门控（critical 不可发布）
- Citation Validator: 数字/证据编号可追溯（v1.9.52）

## 6. 仍建议加固（非阻塞）

| 项 | 说明 |
|----|------|
| Rate limiting | 分析 / 进化寻优等高成本接口可加 per-IP 限流 |
| 下载短时 token | 减少 query 中长期 token 进入代理日志 |
| 审计导出 | 已有基础 audit；可导出给合规复盘 |
| 打包排除 | 发布物勿含 `data/runtime/local_api_token.txt` |

## 7. 自检清单

```bash
# Token 中间件与 CORS
pytest tests/security tests/test_cors.py -q

# Key vault / URL guard
pytest tests/test_url_guard.py -q -k "not network"
```
