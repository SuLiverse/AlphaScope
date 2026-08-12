# Plan 001: 清除已暴露的密钥实物并完成轮换

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- docs/archive-notes/AUDIT-2026-07-01.md scripts/rotate_master_key.py build.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW（操作的是本地副本与构建产物；唯一不可逆步骤要求人工确认）
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

仓库与构建输出目录中存在三处**密钥实物**（不是代码缺陷，是卫生事故）：

1. 一个 44 字符的 `AI_FINANCE_MASTER_KEY` 明文值被提交进 git 跟踪的文档。主密钥用于 AES-GCM 加密数据库里全部 provider API key 密文——任何拿到仓库（含历史）的人都能解密历史密文。提交过的密钥即视为已泄露，即使从 HEAD 删除也必须轮换。
2. `dist/AlphaScope/.env`（gitignored，未提交）含 21 个非空键值，包括主密钥与 9 个 provider 真实 API key（DeepSeek/Claude/GPT/Mimo/SenseNova/Kimi/Finnhub/FRED/Tushare 类型）。这正是会被 zip/拷贝/备份分发的目录。
3. `apps/web/public/runtime-config.js` 与 `dist/AlphaScope/apps/web/dist/runtime-config.js` 各含一个 43 字符的活 `localApiToken`（均 gitignored，未提交）。

**硬性纪律：本计划及任何产出物中绝不复述任何密钥值本身。一律只引用 `file:line` 与凭据类型。**

## Current state

- `docs/archive-notes/AUDIT-2026-07-01.md:36` — git 跟踪文件，含 `AI_FINANCE_MASTER_KEY=<44 字符值>`。核验方式（不打印值）：
  ```bash
  git grep -c "AI_FINANCE_MASTER_KEY" -- docs/
  # 现状输出: AUDIT-2026-07-01.md:1 / RELEASE-NOTES-v1.8.1.md:1 / security.md:1
  # 后两个文件只是提及变量名（无 =值），只有 AUDIT-2026-07-01.md 含真实赋值。
  ```
- `dist/AlphaScope/.env` — 未跟踪文件。核验：`grep -cE "^[A-Z_]+=.+" dist/AlphaScope/.env` → 现状 `21`。
- `scripts/rotate_master_key.py` — 现成的轮换工具（本仓库自带），docstring 说明：备份 `.env` 与 db → 用旧 key 解密 `datasource_credentials`/`model_providers`/`notifier_channels` 三表密文 → 生成新随机 key → 重加密回写 → 更新 `.env`。支持 `--dry-run`，失败可回滚（`.env.bak`/`*.db.bak`）。用法：
  ```
  python scripts/rotate_master_key.py [--env .env] [--db data/db/ai_finance.db] [--dry-run]
  ```
- 本地 API token 由后端启动时自动生成（`ensure_local_api_token`，环境变量 `ALPHASCOPE_LOCAL_API_TOKEN`），删除后重启即重新生成。
- `build.py` 是打包脚本。已验证的事实：发布物 `dist/AlphaScope-portable.zip` 内是占位 runtime-config、无 `.env`（干净）；但松散目录 `dist/AlphaScope/` 被遗留了真实 `.env`。`build.py` 是否有拷贝 `.env` 的步骤**未核实**——Step 5 要先查。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 检查跟踪文件泄露 | `git grep -nE "AI_FINANCE_MASTER_KEY=.\{20,\}" -- docs/` | 清理后无输出 |
| 干跑轮换 | `python scripts/rotate_master_key.py --dry-run` | exit 0，报告将处理的密文行数 |
| 执行轮换 | `python scripts/rotate_master_key.py` | exit 0，`.env` 中 key 已更换（只验长度变化，不打印值） |
| 回归测试 | `python -m pytest tests/test_settings.py tests/test_security_key_vault.py -q` | 全部通过（若后者不存在则只跑前者） |
| Lint | `ruff check backend frontend tests` | exit 0 |

## Scope

**In scope**（只允许改动）:
- `docs/archive-notes/AUDIT-2026-07-01.md`（删除密钥值，替换为脱敏说明）
- `dist/AlphaScope/.env`、`dist/AlphaScope/apps/web/dist/runtime-config.js`（删除或重置为占位——未跟踪的本地文件）
- `apps/web/public/runtime-config.js`（本地未跟踪文件；通过重置 token 再生）
- `build.py`（仅当 Step 5 确认它确实拷贝了 `.env` 时，加一行覆盖保护）
- `tests/test_no_committed_secrets.py`（新建）
- 根目录 `.env`（仅通过 `rotate_master_key.py` 脚本修改，不手工编辑）

**Out of scope**（不要碰）:
- git 历史改写（filter-repo/filter-branch）——见 Step 7，那是需要仓库所有者另行决策的人工操作，本计划不执行。
- `docs/security.md`、`docs/releases/RELEASE-NOTES-v1.8.1.md`——它们只提及变量名，合法。
- 任何 provider 控制台的 key 吊销/换发——执行者无法完成，列入人工清单（Step 6）。
- `seed/ai_finance.db`——已核实只含行情数据，无需处理。

## Git workflow

- Branch: `advisor/001-secret-exposure-cleanup`
- 提交风格（参照 `git log` 的 conventional commits，例如 `fix(api): re-export run_local_backtest_payload without unused import`）：`docs(security): redact committed master key value and add committed-secret guard test`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 基准确认（只读）

运行：
```bash
git grep -c "AI_FINANCE_MASTER_KEY" -- docs/
grep -cE "^[A-Z_]+=.+" dist/AlphaScope/.env
```
预期：第一命令输出 3 行（计数 1/1/1）；第二命令输出 `21`。若数字不符，说明环境已变化——继续前在报告中记录差异（不视为 STOP，除非 AUDIT 文件中已找不到赋值行，那说明泄露已不存在，跳到 Step 4）。

### Step 2: 清除跟踪文档中的密钥值

编辑 `docs/archive-notes/AUDIT-2026-07-01.md` 第 36 行：把 `AI_FINANCE_MASTER_KEY=<值>` 整行替换为：

```
> ~~AI_FINANCE_MASTER_KEY~~ （原值已于 2026-07 审计中发现被误提交，已删除并轮换；教训：审计文档只引用变量名，永不引用值）
```

**Verify**: `git grep -nE "AI_FINANCE_MASTER_KEY=.\{20,\}" -- docs/` → 无输出（exit 1，无匹配）。

### Step 3: 轮换主密钥（本地 .env + db 密文）

```bash
python scripts/rotate_master_key.py --dry-run
python scripts/rotate_master_key.py
```
预期：dry-run 报告各表密文行数；正式运行 exit 0，生成 `.env.bak` 备份。

**Verify**: `python -m pytest tests/test_settings.py -q` → 全部通过（设置读写加解密链路回归）。再手工验证：启动后端 `python -c "from backend.security.key_vault import encrypt_secret, decrypt_secret; assert decrypt_secret(encrypt_secret('probe')) == 'probe'; print('vault ok')"` → 输出 `vault ok`。（若 `key_vault` 无这两个函数名，先 `grep -n "^def \|^class " backend/security/key_vault.py | head` 找到等价的加解密封装再验证；找不到等价封装是 STOP 条件。）

### Step 4: 清理构建产物目录与本地 token

```bash
rm -f dist/AlphaScope/.env dist/AlphaScope/apps/web/dist/runtime-config.js
```
重置本地 API token：编辑根目录 `.env`，删除 `ALPHASCOPE_LOCAL_API_TOKEN=` 整行（若存在），下次启动后端会自动生成新 token 并重写 `apps/web/public/runtime-config.js`。不要手工删除 `apps/web/public/runtime-config.js` 以外的 runtime-config 文件。

**Verify**: `test -f dist/AlphaScope/.env && echo STILL-PRESENT || echo cleaned` → `cleaned`。

### Step 5: 打包链路加固检查

`grep -n "\.env" build.py | head -20` 检查打包脚本是否拷贝 `.env`。

- 若**有**拷贝逻辑：在拷贝后立即用 `.env.example` 覆盖目标（保持发布物为占位），参照 portable zip 已有的正确行为；
- 若**没有**（`.env` 是上次手工运行遗留进 `dist/` 的）：在 `build.py` 的产物收尾处加一行防御性删除 `dist/AlphaScope/.env`（若存在）并打印警告。

**Verify**: `python -c "import ast; ast.parse(open('build.py').read()); print('syntax ok')"` → `syntax ok`；`ruff check build.py` → exit 0。

### Step 6: 新增防回归测试

新建 `tests/test_no_committed_secrets.py`：用 `git ls-files` 枚举跟踪文件，扫描其中形如 `(_API_KEY|_API_SECRET|MASTER_KEY|_TOKEN)=\S{16,}` 的赋值模式（排除 `.env.example`、占位符 `your_*`/`<` 开头的值、以及 `os.environ.get` 等代码形态——只扫文档/配置类文本后缀 `.md/.txt/.yaml/.yml/.js/.example` 中的字面赋值）。断言零匹配。

**Verify**: `python -m pytest tests/test_no_committed_secrets.py -q` → 1 passed。

### Step 7: 人工清单（写进提交说明与报告，不由执行者操作）

1. 到 9 个 provider 控制台吊销并换发 API key（类型清单见 "Why this matters"，值曾经存在于 `dist/AlphaScope/.env`）。
2. git 历史清洗（`git filter-repo --replace-text` 或 BFG）——需仓库所有者决策，会改写历史，协作者需重新克隆。
3. 删除 `rotate_master_key.py` 生成的 `.env.bak` 备份（其中含旧 key），或移出工作区妥善保管。

**Verify**: 无命令——在最终报告中逐条列出。

## Test plan

- 新测试 `tests/test_no_committed_secrets.py`（Step 6），覆盖：干净仓库零匹配（当前态）；用临时构造的含假 key 文本验证扫描器本身能命中（测测试）。
- 回归：`python -m pytest tests/test_settings.py -q` 全绿。
- 结构性参照：`tests/test_settings.py` 的写法（pytest 函数式、无类）。

## Done criteria

- [ ] `git grep -nE "AI_FINANCE_MASTER_KEY=.\{20,\}" -- docs/` 无输出
- [ ] `grep -cE "^[A-Z_]+=.+" dist/AlphaScope/.env 2>/dev/null || echo 0` 输出 `0`（文件已删）
- [ ] 主密钥已轮换且加解密冒烟通过（Step 3 的 `vault ok`）
- [ ] `python -m pytest tests/test_no_committed_secrets.py tests/test_settings.py -q` 全部通过
- [ ] `ruff check backend frontend tests` exit 0
- [ ] `git status` 中无 scope 外文件被修改
- [ ] 提交说明与最终报告包含 Step 7 的三条人工清单
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `scripts/rotate_master_key.py --dry-run` 报错或报告 0 行密文但 db 中实际存在加密 provider（说明脚本与现状不符）。
- `build.py` 中 `.env` 的去向无法确定（既无拷贝也无清理点）。
- 轮换后 `tests/test_settings.py` 出现失败两次仍未解决。
- 发现**其他**跟踪文件中存在类似密钥赋值（扫描器在 Step 6 初次运行就命中计划外文件）——记录文件名与行号，报告，不要自行扩大清理范围。

## Maintenance notes

- 未来任何审计/排障文档：只引用变量名，不引用值。建议把 Step 6 的扫描测试视为长期守门员。
- PR 评审重点：确认 diff 中没有出现任何密钥值；确认 `build.py` 的防御逻辑不影响正常 portable 构建（`python build.py --zip` 可供人工抽查，不在本计划验证范围内）。
- 明确延期：git 历史清洗与 provider key 换发是人工动作；`runtime-config.js` 的分发模型本身（docker 下 token 当静态文件公开）由 `plans/009-docker-token-hygiene.md` 处理。
