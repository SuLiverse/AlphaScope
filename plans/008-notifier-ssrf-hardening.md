# Plan 008: 加固通知渠道的 SSRF 防线（飞书 webhook 主机校验 + SMTP 私网闸门）

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/notifiers.py tests/test_notifiers.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW（合法飞书/lark webhook 仍通过；SMTP 私网默认拦截、显式开关放行）
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

代码库其他地方（provider base_url、新闻链接解析）都走了 `url_guard.validate_public_http_url` 的 SSRF 防线，唯独通知渠道没有：

1. 飞书 webhook 的校验是**子串匹配**——`"feishu.cn" not in webhook and "larksuite" not in webhook` 才拒绝。攻击者构造 `https://evil.example/?q=feishu.cn` 或 `https://feishu.cn.evil.example/` 即可通过，服务器随后向任意地址 POST JSON（token 持有者经 `POST /api/notifiers/{channel}` 配置、`/test` 触发）。
2. `send_email` 的 `smtp_host:smtp_port` 完全用户可控——可向任意内网 host:port 发起带认证的 TCP 会话（配置驱动 SSRF）。私网 SMTP 中继又是本地部署的合理用途，所以默认拦、留显式开关。

## Current state

- `backend/notifiers.py:93-103` — `send_feishu`：
  ```python
  webhook = (webhook or "").strip()
  if not webhook or "feishu.cn" not in webhook and "larksuite" not in webhook:
      return SendResult(False, "feishu", "webhook 缺失或非飞书地址")
  res = _http_post_json(webhook, {"msg_type": "text", "content": {"text": f"{title}\n\n{body}"[:3500]}})
  ```
- `backend/notifiers.py:119-152` — `send_email`：`smtplib.SMTP(smtp_host, port, timeout=15)` / `SMTP_SSL`，host 无任何校验。
- 现有 SSRF 防线：`backend/security/url_guard.py` 提供 `validate_public_http_url`（新闻解析处的用法见 `backend/api/news.py` 的 `_validate_public_http_url`）。**先用 `grep -n "def validate_public_http_url" backend/security/url_guard.py` 确认其签名与参数（是否有 allow_local 之类的开关），按真实签名调用。**
- 配置入口：`backend/api/notifiers.py` 的 `POST /api/notifiers/{channel}` 与 `/test`——本计划**不改** API 层，校验全部收在 `notifiers.py` 的发送函数里。
- 测试：`tests/test_notifiers.py` 已存在（先读，沿用其 mock `_http_post_json`/`smtplib` 的方式，不得真发网络请求）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_notifiers.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/notifiers.py`（`send_feishu` 校验、`send_email` 私网闸门；可新增一个模块级私有辅助函数）
- `tests/test_notifiers.py`（追加用例）

**Out of scope**:
- `backend/api/notifiers.py` —— 端点层不动。
- pushplus/telegram/server 酱等其他渠道 —— telegram 走固定 `api.telegram.org` 域名拼接，pushplus 走固定域名，无此问题。
- 新闻链接解析的重定向链校验（独立发现，M 级，未立项）。
- 通知内容的脱敏策略。

## Git workflow

- Branch: `advisor/008-notifier-ssrf-hardening`
- 提交风格：`fix(security): validate feishu webhook host and gate private SMTP relays`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 飞书 webhook 改为主机名校验 + url_guard

`backend/notifiers.py` 的 `send_feishu`：

1. `from urllib.parse import urlparse`（文件顶部），解析 webhook；要求 `scheme == "https"` 且 `hostname` 等于 `open.feishu.cn`、等于 `open.larksuite.com`，或以 `.feishu.cn` / `.larksuite.com` 结尾——否则返回 `SendResult(False, "feishu", "webhook 缺失或非飞书地址")`（沿用现有错误文案，API 契约不变）。
2. 通过主机校验后，再过一道现有防线：`from backend.security.url_guard import validate_public_http_url`，用其返回的安全 URL 作为 `_http_post_json` 的目标（签名以 Step 0 核实为准；校验抛 ValueError 时同样转为 SendResult(False, ...)）。

**Verify**: `python -c "from backend.notifiers import send_feishu; print(send_feishu('https://evil.example/?q=feishu.cn','t','b').ok, send_feishu('https://feishu.cn.evil.example/hook','t','b').ok)"` → `False False`

### Step 2: SMTP 私网闸门

`backend/notifiers.py` 新增私有辅助 `_smtp_host_allowed(host: str) -> bool`：

- 解析主机：`socket.getaddrinfo(host, None)` 取 IP（解析失败 → 不允许）；
- 全部 IP 为公网（`ipaddress.ip_address(ip)`，排除 `is_private`/`is_loopback`/`is_link_local`/`is_reserved`/`is_multicast`）→ 允许；
- 环境变量 `ALPHASCOPE_ALLOW_PRIVATE_SMTP=1` 时直接允许（内网中继的显式逃生门，在函数 docstring 写明）。

`send_email` 在连接前调用，不允许则 `SendResult(False, "email", "SMTP 主机位于内网/环回, 如需私网中继请设置 ALPHASCOPE_ALLOW_PRIVATE_SMTP=1")`。

**Verify**: `python -c "from backend.notifiers import send_email; r=send_email('127.0.0.1',25,'u','p','a@b.c','d@e.f','t','b'); print(r.ok, r.error[:20])"` → `False SMTP 主机位于内网...`

### Step 3: 测试

`tests/test_notifiers.py` 追加（全程 mock，无真实网络）：

- feishu：`https://open.feishu.cn/open-apis/bot/v2/hook/xxx` 通过校验并调用 `_http_post_json`（mock 断言被调）；`https://feishu.cn.evil.example/`、`https://evil.example/?q=feishu.cn`、`http://open.feishu.cn/...`（非 https）均被拒；
- email：`127.0.0.1` / `192.168.1.10` 默认被拒；monkeypatch 设 `ALPHASCOPE_ALLOW_PRIVATE_SMTP=1` 后放行（mock smtplib）；
- 公网域名解析行为用一个稳定假地址打桩 `socket.getaddrinfo`（不要真解析外部域名）。

**Verify**: `python -m pytest tests/test_notifiers.py -q` → 全过，新增 ≥5 用例。

## Test plan

- 见 Step 3，结构沿用 `tests/test_notifiers.py` 既有 mock 风格。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] Step 1/2 两条 `python -c` 抽查输出符合预期
- [ ] `python -m pytest tests/test_notifiers.py -q` 全过且新增 ≥5 用例
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `validate_public_http_url` 的真实签名/异常类型与本计划假设不符——以源码为准调整调用；若它**不**做私网 IP 拦截（只是格式校验），则在 feishu 路径也补一道与 Step 2 同款的 IP 检查，并在报告中说明。
- 既存用户配置里有合法 webhook 使用 http 或非标准 feishu 域名（查看 `data/` 下 notifier 配置的域名分布——只看域名，不看密钥），如有则改为放行并记录，报告后由人决策。
- `_http_post_json` 内部还会再做跳转/二次请求（若是，重定向链问题与新闻链接解析同类，记录并报告，不在本计划修复）。

## Maintenance notes

- DNS 重绑定（校验时解析为公网、连接时变为内网）是残余风险；彻底解法是连接级固定 IP（`provider_gateway` 的 `create_ssrf_safe_http_client` 已有此机制，但通知渠道量级小、收益低，本计划不迁移）。
- PR 评审重点：主机后缀匹配是否以 `.` 边界（`evilfeishu.cn` 必须被拒——`hostname.endswith(".feishu.cn")` 而非 `"feishu.cn" in host`）；新增环境变量需同步进 `.env.example`（允许顺手加一行注释说明，算本计划范围）。
- 明确延期：`/api/notifiers/{channel}/test` 端点的频率限制依赖全局限流，未单列。
