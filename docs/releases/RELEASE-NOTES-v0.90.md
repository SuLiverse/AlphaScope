# AI-FINANCE v0.90 Release Notes

> Release Candidate - 2026-05-21

## 概述

AI-FINANCE v0.90 是 v1.0 Local 正式版的候选版本。本版本功能冻结，专注于稳定性、测试覆盖和文档完善。

## 系统要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10 / macOS 12 / Ubuntu 20.04 | Windows 11 / macOS 14 / Ubuntu 22.04 |
| Python | 3.10+ | 3.11+ |
| Node.js | 18+ | 20+ |
| 内存 | 8GB | 16GB+ |
| 磁盘空间 | 2GB | 10GB+ |

## 核心功能

### 1. 多 Agent 专家团分析
- 10 位专家协作分析（巴菲特、林奇、缠论、宏观、风控、消息面、资金面、反方、合规、总结）
- 5 家 LLM 厂商异构推理（Claude / GPT / DeepSeek / Mimo / SenseNova）
- 3 种分析模式：标准（快速）、深入（全面）、自动（智能选择）

### 2. K 线图视觉分析
- 上传 K 线截图进行技术分析
- 自动识别图表类型、趋势、支撑位、压力位
- 反查真实行情数据交叉验证

### 3. 多维数据源
- 20+ 数据源自动发现和故障转移
- 行情、新闻、公告、资金流、宏观数据
- 数据质量层：去重、来源评级、异常检测

### 4. 报告管理
- 自动保存分析报告
- Markdown / PDF 导出
- 按股票/日期/模式搜索
- 后验验证追踪决策表现

### 5. 本地运行
- 一键启动（Windows 双击 bat）
- SQLite 本地存储
- 本地配置 API Key
- 无 ChromaDB 优雅降级

## 测试状态

```
Python 测试: 697 passed, 2 skipped
Lint 检查: All checks passed
代码格式: 212 files already formatted
Next.js 构建: 成功 (41.4 kB)
CI: 全绿
```

## 文件结构

```
AlphaScope/
├── AlphaScope-Setup.bat      # 一键安装启动器
├── apps/web/                  # Next.js 主前端
├── backend/                   # FastAPI 后端
├── config/                    # 配置文件
├── data/                      # 本地数据
├── docs/                      # 文档
│   └── user-manual/           # 用户手册
├── frontend/                  # Streamlit 调试台
├── scripts/                   # 启动脚本
└── tests/                     # 测试
```

## 快速开始

### Windows 一键安装
1. 下载并解压项目
2. 双击 `AlphaScope-Setup.bat`
3. 按提示完成安装
4. 编辑 `.env` 填入 API Key
5. 双击桌面快捷方式启动

### 手动安装
```bash
# 安装依赖
pip install -e .
cd apps/web && npm install

# 配置
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动
scripts/start_local.bat
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/conversations` | GET/POST | 对话管理 |
| `/api/chat/stream` | POST | SSE 流式对话 |
| `/api/analysis/run` | POST | 运行 Agent 分析 |
| `/api/vision/analyze` | POST | K 线图分析 |
| `/api/agents` | GET | Agent 配置 |
| `/api/teams` | GET | 专家团列表 |
| `/api/reports/{id}` | GET | 获取报告 |
| `/api/providers/health` | GET | 数据源健康 |
| `/api/costs` | GET | 成本统计 |
| `/api/backtest/stats` | GET | 回测统计 |

## 已知限制

1. **仅支持 A 股** - 美股/港股数据源有限
2. **需要网络** - LLM API 和数据源需要网络连接
3. **单用户** - 不支持多用户并发
4. **无认证** - 无用户登录和权限管理

## 下一步

- v1.0 正式版发布
- 完善用户反馈
- 持续优化性能

## 反馈

- GitHub Issues: https://github.com/TIANWEN-cpu/AlphaScope/issues
