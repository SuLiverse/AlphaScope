# 研策中枢 AlphaScope v1.7.2

发布日期：2026-06-05

v1.7.2 是面向最终交付的一键启动质量补丁。它保留 v1.7.1 的 AkShare 运行时资源打包修复，并进一步清理浏览器实测中暴露的 Recharts 图表尺寸 warning。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.7.2.exe`
- 便携版：`AlphaScope-portable.zip`

如果没有安装 Inno Setup，也可以使用便携版目录：

```powershell
python build.py --zip
dist\AlphaScope\AlphaScope.exe
```

## 修复

- 新增 `StableChartContainer`，先测量图表容器尺寸，再向 Recharts 图表传入稳定的数字宽高。
- 替换 Workbench、Portfolio、Backtesting、MultimodalChart、FundDcaLab 中直接使用 `ResponsiveContainer` 的图表。
- 修复首页、组合与风控、量化回测、K 线/多模态、基金与定投研究室在首次布局或页签切换时可能出现的 `width(-1)` / `height(-1)` console warning。
- 修复 K 线/多模态页本地预览 K 线日期显示错误，避免出现 `05-32`、`05-48` 等非法日期。
- 统一版本号到 `1.7.2`，覆盖 Python 项目版本、前端 package、桌面启动器和安装器脚本。
- 重新生成 Windows portable 目录和 `AlphaScope-portable.zip`。

## 一键启动

1. 下载 `AlphaScope-portable.zip` 并解压，或下载 `AlphaScope-Setup-1.7.2.exe` 安装。
2. 双击 `AlphaScope.exe`。
3. 程序会自动寻找可用本地端口，启动 FastAPI 后端和已构建 Web 页面，并打开浏览器。
4. 首次使用 AI 分析前，在自动创建的 `.env` 中填写至少一个模型 API Key。

源码用户可运行：

```powershell
AlphaScope-Setup.bat
```

## 验证

```bash
npm run lint
npm run build
python build.py --skip-web --zip
```

结果：均通过。Vite 仅保留已有 chunk size / dynamic import 提醒。

额外打包验收：

- `dist/AlphaScope/AlphaScope.exe` 启动成功。
- `/health` 返回 `1.7.2`。
- `/api/prices/600519?limit=3` 返回 `success=true`、`source_status=ok`、`degraded=false`。
- `AlphaScope-portable.zip` 包含 `_internal/pyproject.toml`、`_internal/akshare/file_fold/calendar.json`、`_internal/apps/web/dist/index.html`。
- Browser-Use 打开最终打包页面后，新增 console `warning=0`、`error=0`、Recharts warning `0`。
- Browser-Use 点开 K 线/多模态页后，本地预览 K 线日期为合法日期区间，未再出现非法日期刻度。

## 已知边界

- 外部行情、新闻和模型 Provider 可用性仍取决于用户网络、账号额度和第三方服务状态。
- 未配置真实模型 API Key 时，聊天、报告和多 Agent 分析会进入未配置或失败提示状态。
- PyInstaller 构建阶段可能提示若干可选依赖 warning，本次一键启动、健康检查和行情接口验收不受影响。
