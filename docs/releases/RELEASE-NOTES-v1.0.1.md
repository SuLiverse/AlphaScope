# AI-FINANCE v1.0.1 Windows 前端与启动修复版

> 2026-05-22

## 概述

v1.0.1 是 v1.0 Local 正式版后的补丁版本，重点修复 Windows 本地启动和 Next.js 主前端实际使用中暴露的问题。该版本不改变后端分析能力，目标是让用户打开 `http://localhost:3000` 后看到可用、带样式的正式工作台界面。

## 修复的问题

### 1. v0.85 Windows 一键包遗留问题

- PowerShell 5 在 GB2312 默认编码环境下读取 UTF-8 无 BOM 脚本时，中文字符串可能导致解析错误。
- `start_local.ps1` 通过 `Start-Process -FilePath "npm"` 启动前端，在部分 Windows 环境会误打开 Notepad，导致 3000 端口没有正确启动 Next.js。
- `stop_local.ps1` 使用 `$pid` 变量名，与 PowerShell 内置只读变量冲突，导致停止脚本异常。
- 原停止脚本只停止入口进程，未清理 npm 派生出的 Next.js node 子进程，容易留下旧 dev server。

### 2. v1.0 主前端问题

- `apps/web` 缺少 `postcss.config.js`，Tailwind CSS 在 dev server 中未正确输出。
- 页面 HTML 引用 `/_next/static/css/app/layout.css`，但 CSS 返回 404，导致浏览器只显示裸 HTML。
- 运行 `next build` 后 `.next` 被生产构建覆盖，仍在运行的 dev server 会继续引用不存在的 CSS 路径。
- Next.js 主工作台视觉和信息架构过于骨架化，打开后不像正式产品。
- `/health` 返回版本号仍为 `0.50.0`，与 v1.0 正式版不一致。
- 前端 `package.json` / API client 注释仍停留在旧版本号。

## 本版修复

### Windows 启动稳定性

- PowerShell 脚本改为 UTF-8 BOM，兼容 Windows PowerShell 5 默认编码。
- `start_local.ps1` 优先使用 `npm.cmd` 启动 Next.js。
- `start_local.ps1` 启动前清理 `apps/web/.next`，避免 dev/prod 构建缓存冲突。
- `stop_local.ps1` 改为递归停止进程树。
- `stop_local.ps1` 增加端口清理和项目内残留 Next.js 进程清理。

### 前端样式修复

- 新增 `apps/web/postcss.config.js`：

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- 验证 `/_next/static/css/app/layout.css` 返回 200。
- 验证 CSS 中包含 Tailwind 工具类，例如 `.flex` 和 `bg-slate-950`。

### 主工作台 UI 改进

- 重做 Next.js 首页为三栏金融工作台：
  - 左侧研究控制台
  - 中间主分析区
  - 右侧研究监控面板
- 增加首屏能力卡片、快速开始问题、风险提示和当前研究对象。
- 改进输入区、模式选择、Agent/证据链空态。

### 版本一致性

- FastAPI `app.version`、`/` 和 `/health` 返回版本更新为 `1.0.1`。
- 更新版本断言测试。
- 前端 package 版本更新为 `1.0.1`。

## 验证状态

```text
PowerShell 脚本语法检查: 通过
http://127.0.0.1:3000: 200
/_next/static/css/app/layout.css: 200, Tailwind 工具类存在
/health 版本测试: 2 passed, version=1.0.1
Next.js build: 成功
Python 测试: 697 passed, 2 skipped
Ruff check: All checks passed
Ruff format --check: 216 files already formatted
```

## 升级建议

如果已经运行过 v1.0，本次升级后建议执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_local.ps1
powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1
```

然后重新打开：

```text
http://localhost:3000
```

如果浏览器仍显示旧页面，关闭旧标签页后重新打开，或按 `Ctrl + F5` 强制刷新。
