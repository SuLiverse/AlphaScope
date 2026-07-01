# v1.9.39 — 全面质量审查修复

对 v1.9.39 进行全面代码审查，发现并修复 51 项问题（7 严重 / 9 高危 / 16 中危 / 19 低危），涵盖线程安全、资源泄漏、依赖声明、导入路径、异常处理五大类。完整报告见仓库内 `AUDIT-2026-07-01.md`。

### 改动

**线程安全（严重 / 高危）**
- Database 单例初始化加双检锁（`type(self)._lock`），防止并发实例化竞态
- TaskQueue 新增 `_state_lock` 保护 `_futures` / `_cancelled` 共享状态；所有访问加锁
- runtime/task_queue 的任务对象读写统一在 `self._lock` 下操作
- 新增 `Database.transaction()` 上下文管理器，替代裸 `Database()._conn` 访问，确保写操作持锁
- agent_store 全部改用 `_get_conn()` → `db.transaction()` 路径

**资源泄漏（高危）**
- fund_flow 改用 `with requests.Session() as session:` 确保连接池释放
- provider_gateway 客户端缓存更新时先关闭旧客户端
- TaskQueue / runtime TaskQueue 新增 `shutdown()` 方法，退出时关闭线程池

**导入路径（高危）**
- `from validators import` → `from backend.validators import`（3 处）
- `from agent_modes import` → `from backend.agent_modes import`
- cost_tracker 导入顺序调整，优先 `backend.project_paths`

**异常处理（中危）**
- 新增 `backend/utils/__init__.py` 的 `safe_call()` 共享工具函数，替代 4 处重复 `_safe()` 定义
- `safe_call()` 记录 debug 日志而非静默吞异常

**依赖声明（严重 / 高危）**
- pyproject.toml 补全 `dependencies` 数组（17 包），新增 `quant` / `mlops` optional extras
- requirements-core.txt 补 `cryptography>=43.0`、`python-multipart>=0.0.20`
- requirements-api.txt 补 `python-multipart>=0.0.20`
- alphascope.spec hiddenimports 补 `cryptography`、`cryptography.hazmat.primitives.ciphers.aead`、`multipart`

**配置清理（中 / 低危）**
- 删除重复的 `ruff.toml`（与 pyproject.toml `[tool.ruff]` 重复）
- 删除重复的 `pytest.ini`（与 pyproject.toml `[tool.pytest.ini_options]` 重复）
- docker-compose.yml 移除不存在的 Redis 服务及相关配置
- .gitignore 新增 `analysis_out.json`
- installer/setup.iss 版本号同步 1.9.23 → 1.9.39

### 零回归
- 测试套件 1623 passed / 5 skipped / 1 deselected（`-m "not network"`）
- 无业务逻辑改动、无 API 接口改动、无前端改动
- 所有修复均为基础设施层加固

### 下载
- **AlphaScope-Setup-1.9.39.exe** — Windows 一键安装包（推荐，约 140 MB）
- **AlphaScope-portable.zip** — 免安装便携版（约 212 MB，解压即用）

> 免责声明：本项目用于研究、学习和辅助分析，**不构成投资建议，不荐股、不预测行情、不承诺收益**。
