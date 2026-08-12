# Plan 012: experts.yaml 与成员 prompt 文件按 mtime 记忆化，消除每请求磁盘重读

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/expert_panel.py tests/test_experts_yaml.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（mtime 键控缓存，文件变更自动失效；纯性能优化）
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

每次专家团运行 / 每次 EXPERT 模式聊天 / 每次 experts API 调用，都会重新 `yaml.safe_load` 整个 `experts.yaml` 并对每个成员 `read_text` 一个 prompt 文件（5-8 个）。这些是典型的静态配置热路径读盘。按 `(路径, mtime)` 记忆化后：无变更时每次调用只需每文件一次 `stat`，有变更自动重读——正确性不依赖任何"手动刷新"约定。

## Current state

- `backend/expert_panel.py:148-156` — `load_prompt_file`：每次调用直接 `p.read_text(encoding="utf-8")`。
- `backend/expert_panel.py:160-221` — `load_experts_config_v2`：`yaml.safe_load(p.read_text(...))` + 循环内对每个成员调 `load_prompt_file`。
- `backend/expert_panel.py:225-238` — `load_experts_config`（v1 兼容）：同样每次全量读盘。
- 热调用点（不需要修改，供评估流量）：`backend/expert_panel.py:416`（`load_default_team`）、`backend/ai_assistant/orchestrator.py` 的 EXPERT 分支、`backend/api/experts.py` 的 GET/POST。
- 缓存先例：`backend/security/rate_limit.py` 有按配置签名缓存的惯例（`grep -n "mtime\|_cache" backend/security/rate_limit.py | head` 查看）；本计划用更简单的 `(path, mtime)` 键。
- 测试：`tests/test_experts_yaml.py` 已存在（先读，沿用其 tmp 配置构造方式）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_experts_yaml.py tests/test_experts_api.py tests/test_experts_team_api.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/expert_panel.py`（三个加载函数的记忆化 + 一个 `reload_experts_config()` 清缓存函数）
- `tests/test_experts_yaml.py`（追加用例）

**Out of scope**:
- 所有调用方（api/experts、ai_assistant、expert_panel 内部调用点）——记忆化在加载函数内部完成，调用方零改动。
- experts.yaml 的写路径（设置 UI 保存）——mtime 机制下自动失效，无需挂钩；**但**若发现写路径在同进程内直接改缓存对象（`grep -rn "EXPERTS_YAML_PATH" backend/api/ | grep -i "write\|save\|post"` 排查），则需在该写路径后调 `reload_experts_config()`，那算本计划一部分；发现其他异常则 STOP。
- v1/v2 配置的语义合并逻辑。

## Git workflow

- Branch: `advisor/012-experts-config-memoization`
- 提交风格：`perf(experts): memoize experts.yaml and prompt-file loads by mtime`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: mtime 键控缓存

`backend/expert_panel.py` 新增模块级缓存与小辅助（放在加载函数上方，风格跟随文件内注释习惯）：

```python
_CONFIG_CACHE: dict[str, tuple[float, object]] = {}  # path_str -> (mtime, value)

def _cached_load(path: Path, loader):
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    hit = _CONFIG_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    value = loader(path)
    _CONFIG_CACHE[key] = (mtime, value)
    return value

def reload_experts_config() -> None:
    """清空 experts 配置缓存（设置写路径/测试用）。"""
    _CONFIG_CACHE.clear()
```

应用到三处：

- `load_experts_config_v2`：yaml 解析经 `_cached_load(p, lambda p: yaml.safe_load(p.read_text(encoding="utf-8")))`；**注意**：缓存的是解析出的 `raw` dict，成员构造（`ExpertMemberConfig(...)`）仍在每次调用时执行（便宜），这样 v2 的行为/默认值逻辑不走缓存、无冻结风险。
- `load_experts_config`（v1）：同款缓存 `raw`。
- `load_prompt_file`：按自己的 `(path, mtime)` 缓存文本——成员 prompt 文件改动无需动 yaml 即可生效。

线程安全：GIL 下 dict get/set 原子可接受；不要引入锁把简单缓存复杂化（与 rate_limit 的先例一致则从其惯例）。

**Verify**: `ruff check backend/expert_panel.py` → exit 0；`python -m pytest tests/test_experts_yaml.py -q` → 既有用例全过。

### Step 2: 排查写路径

`grep -rn "experts.yaml\|EXPERTS_YAML_PATH" backend/api/ backend/settings_store.py | grep -viE "load|read"` 找写路径。若有（例如保存专家配置的端点），在其写文件成功后调用 `reload_experts_config()`（防御性；mtime 本应兜住）。

**Verify**: 无写路径 → 在 commit message 记录"无写路径，mtime 自失效"；有 → 对应测试（Step 3 的 b 用例覆盖）。

### Step 3: 测试

`tests/test_experts_yaml.py` 追加：

a. **磁盘读次数**：monkeypatch `Path.read_text` 包计数 spy，连续两次 `load_experts_config_v2()`（同一 tmp yaml）→ spy 计数为 1；
b. **变更自动失效**：修改 tmp yaml（`write_text` + 确保 mtime 变化——必要时 `os.utime` 显式设置递增 mtime）后再 load → 新内容生效，spy 计数 +1；
c. **prompt 文件独立失效**：只改某成员 prompt 文件（不动 yaml）→ `load_prompt_file` 返回新文本；
d. `reload_experts_config()` 后下次 load 重新读盘。

每个用例前后调 `reload_experts_config()` 做隔离。

**Verify**: `python -m pytest tests/test_experts_yaml.py tests/test_experts_api.py tests/test_experts_team_api.py -q` → 全过，新增 ≥4 用例。

## Test plan

- 见 Step 3。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -n "_CONFIG_CACHE" backend/expert_panel.py` 命中且三个加载函数都经过 `_cached_load`
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- 某个加载函数的返回值会被调用方**原地修改**（缓存对象被污染会影响后续调用——`grep -rn "load_experts_config_v2()\.\|load_default_team()\." backend/ | grep -iE "append|extend|\.pop|del |\[.*\] *=" ` 排查；发现原地写则改为缓存拷贝或报告）。
- mtime 在目标文件系统（FAT/某些网络盘）粒度不足导致变更不生效——测试 b 若在本机失败，报告环境信息。
- 发现写路径直接改缓存对象（见 Scope 说明）。

## Maintenance notes

- 未来若给 experts.yaml 加"监听自动重载"类产品功能，`reload_experts_config()` 是现成挂钩点。
- PR 评审重点：缓存的是 `raw` dict 而非 `ExpertMemberConfig` 对象（避免调用方拿到共享可变实例）；mtime 用 `st_mtime`（float）而非 `st_mtime_ns`，与既有代码风格一致即可。
- 明确延期：prompt 渲染本身的 CPU 开销（远低于磁盘 IO）不处理。
