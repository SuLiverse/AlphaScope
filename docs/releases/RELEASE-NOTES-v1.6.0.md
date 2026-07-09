# 研策中枢 AlphaScope v1.6.0

发布日期：2026-05-31

v1.6.0 是一次前端工作台体验和桌面分发发布，重点补齐新闻研究流、可配置多 Agent 圆桌、统一模型路由、K 线诊断、研报生成和 Windows 一键安装。普通用户可以直接下载安装包使用；开发者仍可从源码运行和扩展。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.6.0.exe`
- 便携版：`AlphaScope-portable.zip`

## 新增

- Windows 一键安装包：`python build.py --installer` 会构建 React Web、打包本地 FastAPI 启动器，并生成 `AlphaScope-Setup-1.6.0.exe`。
- 打包版桌面启动器：自动启动本地服务、写入前端运行时 API 地址并打开浏览器。
- GitHub Actions 安装包工作流：tag/release 可产出安装包和便携 zip，便于普通用户直接下载。
- 新闻详情弹层：查看新闻正文、来源、分类、影响、情绪、AI 摘要和相关标的。
- 新闻 AI 助手：支持选中新闻后咨询，也支持解析用户输入的新闻链接。
- 新闻原文跳转：优先打开真实 `sourceUrl`；缺失时降级为基于标题、标的和来源的搜索跳转。
- Agent 编排设置页：在系统设置中统一管理 Agent 名称、角色、职责、提示词、模型、温度、图标、启用状态和数量。
- 可持久化 Agent 配置：前端保存到 localStorage，并在分析请求中通过 `agent_configs` 传给后端。
- 自定义模型 Provider：支持用户填写 OpenAI-compatible Base URL、API Key、模型 ID 和能力标签。
- 模型路由：聊天、新闻助手、研报生成、专家团、K 线多模态诊断、视觉解析和推理分析可按功能选择模型，也可一键使用统一模型。
- 本地知识库入口：嵌入模型可标记后接入本地知识库。
- K 线信息框：补充时间、涨跌幅、成交信息和红绿样式，周 K / 月 K 支持更长时间范围。
- 研报完整正文：生成核心结论、行情趋势、多智能体会签、风控反证和后续跟踪清单。

## 改进

- 新闻源概览改为可收起，避免遮挡新闻列表。
- 专家圆桌页从配置面板改为运行监控视图，保留状态、任务、拓扑和设置入口。
- 系统设置页新增“Agent 编排”页签，配置体验更接近真正的控制台。
- 清理当前前端可见品牌残留和旧内部代号文案。
- 前端 package 名称、版本和 metadata 更新为正式发布形态。
- K 线分析修复上传图片与选中股票诊断对象不一致的问题。
- 研报生成接入真实行情快照，避免全 0 数据导致报告空洞。
- Agent 配置映射兼容前端 `id/prompt` 字段，避免多个自定义 Agent 折叠成同一个 `custom_agent`。
- 当模型 API Key、Provider 或模型名配置异常时，页面会显示清晰的模型链路降级提示，并生成可读的结构化投研底稿。
- 模型错误和 API Key 相关错误做脱敏处理，避免原始异常污染报告正文。

## 验证

在 `apps/web` 下完成：

```bash
npm run lint
npm run build
```

后端语法检查完成：

```bash
python -m py_compile backend\runtime\orchestrator.py backend\agents\financial_agents.py backend\api\tasks.py
```

打包链路完成：

```bash
python build.py --installer
```

结果：

- TypeScript 检查通过。
- Vite 生产构建通过。
- 后端研报任务、运行时编排和 Agent 调用相关模块通过 `py_compile`。
- PyInstaller 便携目录和 Inno Setup 安装包构建通过。
- 构建仍存在已知 chunk size warning，不影响本次发布。
- 本地页面 `http://127.0.0.1:3002/` 可达，Agent 设置迁移、K 线提示框、研报生成和模型降级提示已做浏览器烟测。

## 升级提示

- Agent 配置保存在浏览器 localStorage 键 `alphascope:agent-configs-v1` 中；旧版缓存键会自动迁移。
- 如需恢复默认 Agent 编排，可进入系统设置 -> Agent 编排，点击“恢复默认”。
- 后端若要消费用户自定义 Agent，需要读取分析请求体中的 `agent_configs` 字段。
- 首次使用 AI 功能前，请进入系统设置添加 Provider，检查 Base URL、API Key、模型列表和模型能力标签。
- 若研报页提示“模型鉴权未通过”，说明报告正文处于降级底稿模式，需要修复 Provider 配置后重新生成。

## 免责声明

本项目用于研究、学习和辅助分析，不构成投资建议。新闻、报告、Agent 输出和量化结果都应结合真实数据源、个人风险承受能力和专业判断独立核验。
