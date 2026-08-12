# Plan 009: Docker 部署的 token 卫生——access log 关闭 + token 不再当静态文件公开分发

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- docker-compose.yml backend/security/runtime_config.py apps/web/src/lib/api.ts apps/web/src/App.tsx docs/deployment.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED（改变 docker 部署的前端引导流程；桌面打包路径必须保持原样）
- **Depends on**: 建议排在 `plans/002` 之后（002 先压缩 token 泄露的爆炸半径）
- **Category**: security
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

docker-compose 部署中，API 容器把含 `localApiToken` 的 `runtime-config.js` 写进共享卷，web 容器把它符号链接进静态目录并在 `0.0.0.0:3000` 对外提供。文档（`docs/deployment.md`）明示该部署支持其他主机的浏览器访问——于是**任何能访问 3000 端口的人 `GET /runtime-config.js` 即得全权限 API token**，token 鉴权在远程 docker 场景下完全失效。该机制只对"web 与 API 同处 localhost 信任边界"（桌面打包）才安全。

附带同域问题：token 兼容以 URL query（`?local_token=`）传递（报告下载/SSE 场景），而 docker 下的 uvicorn 没有关 access log——query string 会落进容器日志（桌面 `launcher.py` 已显式 `access_log=False`，docker 命令没有）。`docs/security.md` 自承 query-token 是已知未修缺口；关 access log 是零成本即时缓解。

## Current state

- `docker-compose.yml:51` — API 容器命令：
  ```yaml
  command: ["python", "-m", "uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
  ```
- `docker-compose.yml:58,61,91-96` — 共享卷 `runtime-config:/runtime`，API 侧 `ALPHASCOPE_RUNTIME_CONFIG_DIR=/runtime`；web 侧 `ln -sf /runtime/runtime-config.js /app/dist/runtime-config.js && npm run preview -- --host 0.0.0.0 --port 3000`。
- `backend/security/runtime_config.py:65-86` — `write_dev_runtime_configs(repo_root, local_api_token)`：同一 payload（**含** `localApiToken`）依次写入 `apps/web/public/`、`apps/web/dist/`，以及（当 `ALPHASCOPE_RUNTIME_CONFIG_DIR` 设置时）共享目录：
  ```python
  shared_dir = os.environ.get("ALPHASCOPE_RUNTIME_CONFIG_DIR", "").strip()
  if shared_dir:
      paths.append(Path(shared_dir) / "runtime-config.js")
  ```
- `backend/api/main.py:158-160` — query-token 兼容：`LOCAL_TOKEN_QUERY = "local_token"`（注释说明用于报告下载、任务事件流）。
- `launcher.py:221-228` — 桌面端先例：`uvicorn.Config(..., log_level="warning", access_log=False)`。
- 前端 token 解析：`apps/web/src/lib/api.ts:11` —
  ```ts
  export const LOCAL_API_TOKEN = <runtime-or-vite-env>
  ```
  `:30-34` — 非空时以 `X-AlphaScope-Local-Token` header 发出。`apps/web/index.html:12` 加载 `/runtime-config.js`。
- 桌面打包路径（`write_runtime_config(..., packaged=True)`，`runtime_config.py:50-62`）写 token 是**安全的**（localhost 边界），本计划不动它。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 后端目标测试 | `python -m pytest tests/ -q -k "runtime_config or local_token" ` | 全部通过 |
| 前端测试 | `npm --prefix apps/web test` | 全部通过 |
| 前端 lint | `npm --prefix apps/web run lint` | exit 0（eslint + tsc） |
| 后端回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| compose 校验 | `docker compose config -q`（无 docker 环境则跳过并说明） | exit 0 |

## Scope

**In scope**:
- `docker-compose.yml`（uvicorn 命令加 `--no-access-log`）
- `backend/security/runtime_config.py`（共享卷副本 token 置空）
- `apps/web/src/lib/api.ts`（token 解析顺序 + sessionStorage 读写，抽纯函数）
- `apps/web/src/App.tsx`（token 缺失时的引导门；先读该文件确认结构）
- `apps/web/src/lib/apiToken.test.ts`（新建，vitest）
- `tests/test_runtime_config.py`（新建）
- `docs/deployment.md`（更新 token 分发说明段落）

**Out of scope**:
- query-token 机制本身改短期一次性下载 token（`docs/security.md` 的规划项，独立改造，不在本计划）。
- 桌面打包/launcher 路径（`packaged=True` 的 runtime-config 继续带 token）。
- SSE/下载链接继续用 query-token——access log 关闭后日志泄露面已消除；浏览器历史残留属已记录的可接受风险。
- `docker-compose.yml` 其他服务/资源限制。

## Git workflow

- Branch: `advisor/009-docker-token-hygiene`
- 提交风格：`fix(security): stop publishing local API token from docker web container`（建议 3 个 commit：access log / 后端置空+测试 / 前端引导+测试+文档）
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 关闭 docker 下 uvicorn access log

`docker-compose.yml:51` 的命令数组末尾追加 `"--no-access-log"`（保持 JSON 数组形式）。注释一行说明：query-token 兼容期间防止 token 落容器日志。

**Verify**: `docker compose config -q` → exit 0（无 docker 环境：`python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"` → exit 0）。

### Step 2: 共享卷 runtime-config 不再携带 token

`backend/security/runtime_config.py` 的 `write_dev_runtime_configs`：`apps/web/public` 与 `apps/web/dist` 两处**保持带 token**（本地源码开发场景，信任边界同桌面）；仅 `shared_dir`（docker 共享卷）副本用 `local_api_token=""` 构造第二份 payload 写入。函数 docstring 更新说明这一分流及原因。

新建 `tests/test_runtime_config.py`：monkeypatch `ALPHASCOPE_RUNTIME_CONFIG_DIR` 指向 tmp_path，调 `write_dev_runtime_configs`，断言共享副本 `localApiToken == ""` 且本地副本 token 原样。结构参照 `tests/test_settings.py` 的 tmp_path/monkeypatch 用法。

**Verify**: `python -m pytest tests/test_runtime_config.py -q` → 全过。

### Step 3: 前端 token 引导（无 token 时用户输入一次）

`apps/web/src/lib/api.ts`：

1. 抽出纯函数（便于 node 环境单测）：
   ```ts
   export function resolveLocalToken(cfg?: string, stored?: string, env?: string): string {
     return cfg || stored || env || '';
   }
   ```
   实际取值改为 `resolveLocalToken(runtimeConfig?.localApiToken, sessionStorage.getItem('alphascope.localToken') ?? undefined, import.meta.env.VITE_LOCAL_API_TOKEN)`（保持原优先级：runtimeConfig 优先）。
2. 新增 `export function storeLocalToken(token: string)` → `sessionStorage.setItem('alphascope.localToken', token)` 并刷新内存值（若 `LOCAL_API_TOKEN` 是模块级 const，重构为 `getLocalToken()` 函数导出，引用点同步改——`grep -rn "LOCAL_API_TOKEN" apps/web/src` 找全引用）。

`apps/web/src/App.tsx`：顶层加一个轻量 gate——挂载时用既有 `fetchApi` 探测一个需鉴权的 GET（如 `/api/settings/preferences`）；若抛 401/403 且 `getLocalToken()` 为空，渲染一个最小 token 输入页（输入 → `storeLocalToken` → 重试），成功前不渲染主界面。UI 风格参照 App 内现有错误/空态组件；不要引入新依赖。

新建 `apps/web/src/lib/apiToken.test.ts`：node 环境纯函数用例（优先级顺序、空值回退链）。

**Verify**: `npm --prefix apps/web test` → 全过；`npm --prefix apps/web run lint` → exit 0。

### Step 4: 文档更新

`docs/deployment.md` 的 docker 段落（"API 容器会生成本地 Token，并通过只读共享卷把运行时配置交给 Web 容器"一带）改写为：token 不再随静态文件分发；远程访问时首次打开 Web 会要求输入一次 token（存 sessionStorage，关页即清）；token 可在 API 容器日志或根 `.env` 的 `ALPHASCOPE_LOCAL_API_TOKEN` 查看。

**Verify**: `grep -n "localApiToken\|共享卷" docs/deployment.md | head` → 新表述就位。

## Test plan

- 后端：`tests/test_runtime_config.py`（Step 2）。
- 前端：`apps/web/src/lib/apiToken.test.ts`（Step 3，node 环境纯函数，无需 jsdom）。
- 回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 与 `npm --prefix apps/web test && npm --prefix apps/web run lint` 全绿。

## Done criteria

- [ ] `grep -n "no-access-log" docker-compose.yml` 命中
- [ ] 共享卷 payload 不含 token（`tests/test_runtime_config.py` 断言）
- [ ] 前端 `npm --prefix apps/web test && npm --prefix apps/web run lint` exit 0
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] 桌面打包路径（`packaged=True`）仍写入 token（`grep -n "local_api_token" backend/security/runtime_config.py` 确认该分支保留）
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `App.tsx` 结构不支持顶层 gate（例如已有全局鉴权/引导机制——若有，接入它而不是另起一套，并在报告中说明）。
- 前端有多个 `LOCAL_API_TOKEN` 引用点且其中某些在模块加载期固化值（`grep` 后发现重构面超过 3 个文件）——记录并报告，评估是否改为只改 api.ts 内部取值。
- 本地源码开发流程（`npm run dev` + 本地后端）在 Step 2 后拿不到 token——本地 `apps/web/public/runtime-config.js` 必须仍带 token，若被误改立即回退该 hunk。
- `docs/deployment.md` 所述部署方式与 compose 现状已不一致（文档漂移）——按 compose 现状为准重写该段并记录。

## Maintenance notes

- 部署后运维变化：远程用户首次打开需输入 token；升级既有 docker 部署时要在 release note 写明此行为变化。
- PR 评审重点：三条 payload 写入路径的 token 分流是否正确（本地两份带、共享一份空）；gate 的探测端点不得是写路径；sessionStorage（而非 localStorage）选型理由——关页即清，降低共享机器残留。
- 明确延期：query-token → 短期一次性 token 兑换（`docs/security.md:51` 的规划项）；CORS 非本机来源的审计；`_archive/` 旧构建不在处理范围。
