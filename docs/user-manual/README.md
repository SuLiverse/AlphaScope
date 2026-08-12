# 研策中枢 AlphaScope 用户手册

> 本地运行的 AI 投研与量化决策工作台

## 什么是研策中枢 AlphaScope？

研策中枢 AlphaScope 是一个本地运行的 AI 投研与量化决策工作台，通过多个 AI Agent 协作产出投资研究报告，并整合新闻、证据链、量化回测和本地设置管理。

核心能力：
- 多 Agent 专家团协作分析（10 位专家）
- 5 家 LLM 厂商异构推理（Claude / GPT / DeepSeek / Mimo / SenseNova）
- K 线图视觉分析
- 行情 / 新闻 / 公告 / 资金流多维数据
- 带证据链、风险提示、置信度的研究报告
- 本地保存所有会话和报告

## 目录

1. [安装指南](01-installation.md) - 环境准备与安装步骤
2. [快速开始](02-quickstart.md) - 首次使用流程
3. [模型接入配置](03-model-config.md) - 配置 LLM API Key
4. [数据源接入](04-data-sources.md) - 配置行情和新闻数据源
5. [专家团使用](05-expert-panel.md) - 使用和自定义专家团
6. [K 线图分析](06-kline-analysis.md) - 上传图片进行视觉分析
7. [报告管理与导出](07-reports.md) - 查看、搜索、导出报告
8. [常见问题](08-troubleshooting.md) - 故障排除与 FAQ

## 适用人群

- 个人投资研究者
- 量化/投研爱好者
- AI 工作流玩家
- 需要本地资料分析的用户

## 系统要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10 / macOS 12 / Ubuntu 20.04 | Windows 11 / macOS 14 / Ubuntu 22.04 |
| Python | 3.11 | 3.12 |
| Node.js | 20.19.x 或 22.12+ | 22.12+ LTS |
| 内存 | 8GB | 16GB+ |
| 磁盘空间 | 2GB | 10GB+（含数据缓存） |
| 网络 | 需要（访问 LLM API 和数据源） | 稳定宽带 |

## 快速链接

- [GitHub 仓库](https://github.com/TIANWEN-cpu/AlphaScope)
- [问题反馈](https://github.com/TIANWEN-cpu/AlphaScope/issues)
