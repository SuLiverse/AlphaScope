"""
Startup: 应用启动钩子。

职责：
- 启动数据采集调度器
- 初始化 Schema 升级
- 发现插件
- 启动定时监控
"""

import logging
import threading

logger = logging.getLogger(__name__)


def startup():
    """应用启动时调用"""
    logger.info("[Startup] AlphaScope 启动初始化...")

    # 1. Schema 升级
    _upgrade_schema()

    # 2. 发现插件
    _discover_plugins()

    # 3. 启动定时监控（后台线程）
    _start_monitoring()

    logger.info("[Startup] 启动初始化完成")


def _upgrade_schema():
    """执行 Schema 升级"""
    try:
        from backend.storage.db import Database
        from backend.storage.schema_upgrade import upgrade_schema, get_table_count

        db = Database()
        conn = db.get_connection()
        before = get_table_count(conn)
        new_tables = upgrade_schema(conn)
        after = get_table_count(conn)
        if new_tables:
            logger.info(
                f"[Startup] Schema 升级: {before} → {after} 表 (+{len(new_tables)})"
            )
    except Exception as e:
        logger.warning(f"[Startup] Schema 升级失败: {e}")


def _discover_plugins():
    """发现并加载插件"""
    try:
        from backend.runtime.plugin_system import get_plugin_manager

        pm = get_plugin_manager()
        plugins = pm.list_plugins()
        if plugins:
            logger.info(f"[Startup] 发现 {len(plugins)} 个插件")
    except Exception as e:
        logger.warning(f"[Startup] 插件发现失败: {e}")


def _start_monitoring():
    """启动定时监控（后台线程, 每 10 分钟扫一次自选股告警）"""
    try:
        import time as _time

        from backend.ingestion.scheduled_reports import get_scheduled_report_manager

        # 触发单例创建
        get_scheduled_report_manager()

        def _scan_loop():
            # 启动后先 sleep 一段, 避免与 provider 注册抢资源
            _time.sleep(15)
            while True:
                try:
                    get_scheduled_report_manager().check_alerts(persist=True)
                except Exception as exc:  # 监控线程绝不能因异常退出
                    logger.debug(f"[Monitor] 扫描告警失败: {exc}")
                _time.sleep(600)  # 10 分钟一次

        thread = threading.Thread(target=_scan_loop, daemon=True)
        thread.start()
        logger.info("[Startup] 定时监控已启动 (每 10 分钟扫描自选股告警)")
    except Exception as e:
        logger.warning(f"[Startup] 定时监控初始化失败: {e}")


def auto_startup():
    """自动启动（在后台线程中执行，不阻塞主进程）"""
    thread = threading.Thread(target=startup, daemon=True)
    thread.start()
