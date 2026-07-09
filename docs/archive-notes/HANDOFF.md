# AlphaScope 项目交接文档 (v1.0.1)

## 项目概述

AlphaScope 是一个多 Agent 金融分析工作台，通过异构 LLM 模型协作产出投资研究。

- GitHub: https://github.com/TIANWEN-cpu/AlphaScope
- 本地路径: D:\研策中枢 AlphaScope\AlphaScope
- 分支: main
- 最新版本: v1.0.1
- CI: 全绿 (lint-and-test + web-build + docker-build)

## 版本历史

| 版本 | 内容 |
|------|------|
| v0.40–v0.40.8 | 工程稳定化、FastAPI 产品化、Agent 标准化、数据源证据链、K线分析、Next.js 前端、安全部署、Smoke/Contract 测试 |
| v0.41–v0.45 | Local Launcher、Settings Center、数据目录标准化、Report Center、Task Center |
| v0.46–v0.50 | 主工作台重构、Agent 编辑器、文件与知识库、证据链引擎、Local Beta |
| v0.51–v0.55 | 行情数据标准化、技术面分析、基本面分析、新闻/公告/事件分析、K线视觉正式版 |
| v0.66–v0.70 | 本地安全加固、合规输出、日志与诊断、性能优化、Local RC |
| v0.81 | 用户手册（8 章完整文档） |
| v0.85 | Windows 一键启动器 |
| v0.90 | Release Candidate |
| v1.0 | 正式版发布 |
| v1.0.1 | Windows 前端启动修复 + 性能优化 + 安全加固 |

## 项目统计

- Python 测试: 697 个通过
- API 端点: 87 个 (FastAPI)
- 前端: Next.js 15 + React 19 build 通过
- 专家团: 10 人默认配置
- 数据源: 20+ Provider
- 文档: 28 份 (docs/)
- 用户手册: 8 章

## 关键文件

```
backend/
├── api/main.py              # FastAPI 主入口 (同步端点，不阻塞事件循环)
├── api/                     # 12 个路由模块 (settings/reports/tasks/agents/knowledge/evidence/prices/technical/fundamentals/news/vision/diagnostics)
├── schemas/api.py           # API 请求/响应 Pydantic 模型
├── ai_assistant/
│   ├── orchestrator.py      # 对话编排器(FREE/STANDARD/DEEP/EXPERT/VISION)
│   ├── conversation_store.py # 对话持久化 (LIKE 转义修复)
│   └── compliance.py        # 合规检查
├── quality/evidence_aggregator.py  # 多源交叉验证 (并行 provider 调用)
├── teams/team_loader.py     # 专家团加载 (带 TTL 缓存)
├── providers/registry.py    # Provider 自动发现 + 优先级路由
├── providers/base.py        # Provider 基类 (UNHEALTHY 标签修复)
├── cache.py                 # TTLCache (新增 cleanup_expired)
└── security/                # AES-GCM 加密 + 日志脱敏

apps/web/src/
├── app/page.tsx             # 主页面 (useMemo 优化)
├── app/error.tsx            # 全局错误边界
├── components/              # MessageBubble(React.memo)/ChatInput/Sidebar/AnalysisPanel
├── hooks/useChat.ts         # 状态管理 hook (ref loading guard)
└── lib/api.ts               # API client (deleteConversation 错误处理)

config/
├── experts.yaml             # 10 人专家团
├── models.yaml              # 3 种分析模式
└── data_sources.yaml        # Provider 配置
```

## v1.0.1 性能优化清单

| 优化项 | 文件 | 改动 |
|--------|------|------|
| async→sync 端点 | api/main.py | 所有阻塞 I/O 端点从 `async def` 改为 `def`，FastAPI 自动线程池调度 |
| YAML 缓存 | teams/team_loader.py | `load_teams()` 带 60s TTL 缓存，避免每次请求读磁盘 |
| 并行 provider | quality/evidence_aggregator.py | `ThreadPoolExecutor` 并行调用，15s 超时 |
| LIKE 转义 | conversation_store.py | 搜索时转义 `%` 和 `_` 通配符 |
| SHA-256 | api/main.py + api/knowledge.py | 文件哈希从 MD5 改为 SHA-256 |
| 路径遍历防护 | api/reports.py | `..` 和 `/` 前缀检查 |
| 输入校验 | schemas/api.py, api/prices.py | message 10000 字符限制，days 1-365 范围 |
| React.memo | MessageBubble.tsx | 防止流式更新时全量重渲染 |
| useMemo | page.tsx | lastAssistant 避免每次渲染数组翻转 |
| loading ref | useChat.ts | 用 ref 替代 state 作为 guard，避免 sendMessage 重建 |
| error.tsx | app/error.tsx | Next.js 全局错误边界 |
| 删减依赖 | package.json | 移除未使用的 recharts/clsx/tailwind-merge |

## 本地运行

```bash
# FastAPI
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# Next.js
cd apps/web && npm install && npm run dev

# Docker (全部服务)
docker-compose up -d

# 测试
python -m pytest tests/ -q
make lint
```

## 工程规范

- 每个 milestone 必须：写计划 → 实现 → 测试 → lint → commit → tag → push → release
- 测试失败优先修，不跳到新功能
- 不提交 .venv/node_modules/.next/缓存
- 不删除 .claude
- 所有 API 返回统一 ApiResponse 格式
- 金融输出必须包含合规声明

## 下一步可选工作 (v1.1)

1. React/Next.js 前端完善（K 线图页面、新闻页面、资金流页面）
2. 异步 SSE 流式（orchestrator 改为异步生成器）
3. Auth 认证（API Key 或 session token）
4. 更多 Provider 健康追踪接入
5. Backtest 可视化
6. 多语言支持
7. 前端响应式布局（移动端适配）
8. 虚拟列表（长对话性能）
