# AI-FINANCE v1.0 Local 正式版

> 2026-05-21

## 概述

AI-FINANCE v1.0 Local 是首个正式版本。这是一个本地运行的 AI 金融分析工作台，通过多个 AI Agent 协作产出投资研究报告。

## 核心功能

### 1. 一键启动
- Windows 双击 `AlphaScope-Setup.bat` 安装
- 桌面快捷方式启动
- 自动检查环境和依赖

### 2. 主工作台
- Next.js 现代化界面
- SSE 流式对话
- 响应式设计

### 3. API 配置
- 支持 5 家 LLM 厂商
- 界面配置 API Key
- 连接测试

### 4. 专家团分析
- 10 位专家协作
- 3 种分析模式
- 审稿员和主席总结

### 5. K 线图分析
- 上传图片识别
- 技术指标提取
- 真实数据交叉验证

### 6. 文件上传
- 支持图片/PDF/CSV/Excel
- 20MB 大小限制
- 本地存储

### 7. 报告保存
- 自动保存分析报告
- 按股票/日期搜索
- 历史记录持久化

### 8. 报告导出
- Markdown 格式
- PDF 格式
- 批量导出

### 9. 历史记录
- SQLite 本地存储
- 会话历史
- 下次启动仍可查看

### 10. 本地备份恢复
- `scripts/backup_local.py`
- `scripts/restore_local.py`
- 数据目录可备份

### 11. 完整文档
- 8 章用户手册
- API 文档
- 架构文档

### 12. 测试全绿
- 697 个测试通过
- CI 全绿
- Lint 和格式化通过

## 系统要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10 / macOS 12 / Ubuntu 20.04 | Windows 11 / macOS 14 / Ubuntu 22.04 |
| Python | 3.10+ | 3.11+ |
| Node.js | 18+ | 20+ |
| 内存 | 8GB | 16GB+ |
| 磁盘空间 | 2GB | 10GB+ |

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

## 文件结构

```
AlphaScope/
├── AlphaScope-Setup.bat      # 一键安装启动器
├── apps/web/                  # Next.js 主前端
├── backend/                   # FastAPI 后端
│   ├── api/                   # API 端点
│   ├── agents/                # Agent 配置
│   ├── teams/                 # 专家团
│   ├── providers/             # 数据源
│   ├── vision/                # 视觉分析
│   └── storage/               # 本地存储
├── config/                    # 配置文件
│   ├── experts.yaml           # 专家团配置
│   ├── models.yaml            # 模型配置
│   └── data_sources.yaml      # 数据源配置
├── data/                      # 本地数据
│   ├── db/                    # SQLite 数据库
│   ├── uploads/               # 上传文件
│   ├── reports/               # 分析报告
│   ├── cache/                 # 缓存
│   └── logs/                  # 日志
├── docs/                      # 文档
│   └── user-manual/           # 用户手册
├── frontend/                  # Streamlit 调试台
├── scripts/                   # 启动脚本
└── tests/                     # 测试
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/conversations` | GET/POST | 对话管理 |
| `/api/chat/stream` | POST | SSE 流式对话 |
| `/api/analysis/run` | POST | 运行 Agent 分析 |
| `/api/vision/analyze` | POST | K 线图分析 |
| `/api/files/upload` | POST | 文件上传 |
| `/api/agents` | GET | Agent 配置 |
| `/api/teams` | GET | 专家团列表 |
| `/api/models/providers` | GET | 模型供应商 |
| `/api/reports/{id}` | GET | 获取报告 |
| `/api/providers/health` | GET | 数据源健康 |
| `/api/costs` | GET | 成本统计 |
| `/api/backtest/stats` | GET | 回测统计 |
| `/api/search` | GET | 网页搜索 |

## 测试状态

```
Python 测试: 697 passed, 2 skipped
Lint 检查: All checks passed
代码格式: 212 files already formatted
Next.js 构建: 成功 (41.4 kB)
CI: 全绿
```

## 已知限制

1. **仅支持 A 股** - 美股/港股数据源有限
2. **需要网络** - LLM API 和数据源需要网络连接
3. **单用户** - 不支持多用户并发
4. **无认证** - 无用户登录和权限管理

## 反馈

- GitHub Issues: https://github.com/TIANWEN-cpu/AlphaScope/issues
