# 研策中枢 AlphaScope v1.4.2

> 2026-05-28

v1.4.2 是品牌迁移与本地体验稳定性补丁。项目正式更名为 **研策中枢 AlphaScope**，仓库地址迁移到 `https://github.com/TIANWEN-cpu/AlphaScope`；同时修复真实浏览器体验中暴露的本地回测、新闻模块和系统设置问题。

## Highlights

- 项目品牌与 README 迁移为研策中枢 AlphaScope。
- 本地回测按钮不再因为一次后端离线或策略状态过期而卡死；运行前会自动刷新本地状态。
- 新闻模块保留上次成功结果，接口抖动时不再直接清空列表。
- 新闻出库层修复历史乱码文本，前端资讯列表恢复正常中文展示。
- 系统设置新增真实偏好设置持久化接口，基础设置、网络节点、安全组、数据管理不再是占位面板。

## Fixed

### Local Quant Lab

- `运行本地回测` 支持状态自恢复：若本地引擎或策略列表状态过期，点击运行会先刷新 `/api/quant/status` 与 `/api/quant/strategies`。
- 新增前端“刷新状态”入口，方便用户手动恢复后端重启后的状态。
- 策略列表刷新后会保留当前策略；当前策略不存在时自动切换到可用策略。
- 回测失败提示明确指向本地后端 8000 和 quant 接口状态。

### News Terminal

- 新闻刷新失败时保留当前列表，并在状态栏说明“已保留上次成功结果”。
- 空态增加“重新同步”操作，降低用户误以为模块永久不可用的概率。
- 后端 `news_store` 对旧数据中的 UTF-8/latin1 乱码字段做保守修复，覆盖新闻标题、摘要、来源和公告字段。
- 公告源为空时仍可使用相关新闻作为降级替代，并清楚标记降级来源。

### Settings Center

- 新增 `GET /api/settings/preferences`。
- 新增 `PUT /api/settings/preferences`。
- 后端新增 `app_preferences` SQLite 表，保存应用偏好设置。
- 基础设置、网络节点、安全组、数据管理四个页签接入真实表单和保存操作。
- 偏好设置会做类型修正与边界限制，避免无效数值污染配置。

### Documentation

- README 标题、简介和截图 alt 文案更新为研策中枢 AlphaScope。
- CI、Release、clone 链接迁移到 `TIANWEN-cpu/AlphaScope`。
- 前端 README 同步新品牌名。

## Verification

Targeted backend and frontend regression:

```text
npm run lint
python -m pytest tests/test_settings.py tests/test_quant_api.py tests/test_news_store.py -q

52 passed
```

Runtime/browser checks:

```text
Frontend: http://127.0.0.1:3000
Backend:  http://127.0.0.1:8000

/api/quant/status
  can_run_backtest=true
  strategy_count=3

/api/news?symbol=600519&limit=1
  title=8股今日获机构买入评级
  source=证券时报网

/api/settings/preferences
  general.default_symbol=600519
```

Browser smoke checks covered:

- Local quant backtest completes and renders result metrics.
- News terminal shows Chinese news content without obvious mojibake.
- Settings tabs render editable forms instead of placeholder text.
- Default symbol preference saves, persists through reload, and was restored to `600519` after testing.

## Known Notes

- Local runtime artifacts under `artifacts/` and `test-results/` are not part of this release.
- External data source availability still depends on local network and third-party services.
- Existing historical docs may still mention the old repository name where they describe legacy installation packages or past plans.

