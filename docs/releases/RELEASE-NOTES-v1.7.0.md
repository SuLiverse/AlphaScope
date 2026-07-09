# 研策中枢 AlphaScope v1.7.0

发布日期：2026-06-01

v1.7.0 是一次安全与真实性修复发布，重点收紧知识库上传、Workbench 上传确认、分析输入保护、新闻/技术资源边界和 Provider 模型列表超时隔离。目标是保持现有体验不大改架构，同时让关键路径更可验证、可回滚。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.7.0.exe`
- 便携版：`AlphaScope-portable.zip`

## 修复

- 知识库上传文件名不再直接信任客户端原始文件名；保存前会去除路径组件并规范化非法字符。
- 知识库上传保存路径继续保留内容 hash 前缀，降低冲突风险。
- Workbench 材料上传改为真实调用 `/api/knowledge/upload`，仅在后端确认成功后显示成功状态。
- Workbench 上传失败时显示后端或网络错误，不再乐观更新本地成功状态。
- `/api/analysis/run` 改为基于真实行情构造分析上下文。
- 空行情或零值行情会返回结构化失败，避免后端生成未标注的正常分析成功响应。
- 新闻接口增加 `limit`、`days`、`window` 上限。
- 技术指标接口增加 `limit` 和 `lookback` 上限。
- Provider 模型列表调用移入 worker thread 并增加超时，避免阻塞 async API 路径。

## 测试

- 新增 `tests/test_upload_safety.py`，覆盖 traversal-style 文件名和规范化文件名保存路径。
- 新增 `tests/test_analysis_guardrails.py`，覆盖空行情和零值行情拒绝。
- 新增/更新资源限制与设置超时测试，覆盖新闻、技术指标和 Provider 模型列表边界。

## 验证

```bash
python -m pytest tests/test_upload_safety.py tests/test_resource_limits.py tests/test_analysis_guardrails.py tests/test_settings.py -q
```

结果：`42 passed`

```bash
npm run lint
npm run build
```

结果：TypeScript 检查和 Vite 生产构建通过。构建仍保留既有 Vite chunk size / dynamic import warning，不影响发布。

## 升级提示

- Workbench 上传现在依赖后端 `/api/knowledge/upload` 可用；后端不可用时会显示失败而不是本地成功。
- 分析接口在无有效行情时会明确失败；前端已标注的 local preview / fallback 仍保留为预览设计，不属于未标注的后端成功响应。
- 如果需要继续收紧通用 `/api/files/upload` 文件名处理，可作为后续独立安全修复。

## 免责声明

本项目用于研究、学习和辅助分析，不构成投资建议。新闻、报告、Agent 输出和量化结果都应结合真实数据源、个人风险承受能力和专业判断独立核验。
