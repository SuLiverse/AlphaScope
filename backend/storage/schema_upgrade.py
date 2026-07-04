"""
Schema Upgrade: 数据库 Schema 升级。

架构文档要求 15+ 张表，当前只有 8 张。
本模块添加缺失的表，为 PostgreSQL 迁移做准备。
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

# 架构文档要求的完整 Schema
FULL_SCHEMA = """
-- 用户表 (Phase: multi-user)
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE,
    password_hash TEXT,
    role TEXT DEFAULT 'user',
    display_name TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 工作空间 (Phase: multi-user)
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    owner_id TEXT REFERENCES users(id),
    name TEXT NOT NULL,
    plan TEXT DEFAULT 'free',
    created_at REAL NOT NULL
);

-- 对话表 (已在 conversation_store.py 中创建)
-- CREATE TABLE IF NOT EXISTS ai_conversations ...
-- CREATE TABLE IF NOT EXISTS ai_messages ...

-- 模型供应商配置
CREATE TABLE IF NOT EXISTS model_providers (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    name TEXT NOT NULL,
    type TEXT DEFAULT 'openai_compatible',
    base_url TEXT,
    encrypted_api_key TEXT,
    enabled INTEGER DEFAULT 1,
    config_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 模型配置
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    provider_id TEXT REFERENCES model_providers(id),
    model_name TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    capabilities TEXT DEFAULT '[]',
    context_window INTEGER DEFAULT 4096,
    price_input REAL DEFAULT 0,
    price_output REAL DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at REAL NOT NULL
);

-- Agent 配置
CREATE TABLE IF NOT EXISTS agent_configs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    provider TEXT DEFAULT 'deepseek',
    model TEXT DEFAULT 'deepseek-chat',
    tools TEXT DEFAULT '[]',
    temperature REAL DEFAULT 0.3,
    max_tokens INTEGER DEFAULT 400,
    output_schema TEXT DEFAULT '{}',
    card_style TEXT DEFAULT 'default',
    enabled INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 专家团配置
CREATE TABLE IF NOT EXISTS agent_teams (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    workflow_config TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 专家团成员
CREATE TABLE IF NOT EXISTS agent_team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT REFERENCES agent_teams(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    role TEXT DEFAULT 'member',
    sort_order INTEGER DEFAULT 0,
    config_json TEXT DEFAULT '{}'
);

-- 数据源连接器
CREATE TABLE IF NOT EXISTS data_connectors (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    auth_config TEXT DEFAULT '{}',
    permission_scope TEXT DEFAULT '[]',
    enabled INTEGER DEFAULT 1,
    health_status TEXT DEFAULT 'unknown',
    last_success_at REAL,
    last_error_at REAL,
    last_error TEXT DEFAULT '',
    call_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- 文档库
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    source_type TEXT DEFAULT 'upload',
    source_url TEXT DEFAULT '',
    title TEXT NOT NULL,
    content_hash TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    trust_score REAL DEFAULT 0.5,
    created_at REAL NOT NULL
);

-- 文档分块
CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding_id TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}'
);

-- 工具调用日志
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT DEFAULT '',
    agent_id TEXT DEFAULT '',
    tool_name TEXT NOT NULL,
    input_json TEXT DEFAULT '{}',
    output_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'ok',
    latency_ms REAL DEFAULT 0,
    created_at REAL NOT NULL
);

-- 分析任务
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT DEFAULT '',
    task_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    input_json TEXT DEFAULT '{}',
    output_json TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    started_at REAL,
    completed_at REAL,
    created_at REAL NOT NULL
);

-- 分析报告
CREATE TABLE IF NOT EXISTS analysis_reports (
    id TEXT PRIMARY KEY,
    conversation_id TEXT DEFAULT '',
    title TEXT NOT NULL,
    summary TEXT DEFAULT '',
    markdown TEXT DEFAULT '',
    citations TEXT DEFAULT '[]',
    risk_level TEXT DEFAULT 'medium',
    confidence REAL DEFAULT 0,
    agent_models TEXT DEFAULT '{}',
    created_at REAL NOT NULL
);

-- 审计日志 (已在 storage/backend.py 中创建)
-- CREATE TABLE IF NOT EXISTS audit_logs ...

-- API Key 管理
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT DEFAULT 'default',
    provider TEXT NOT NULL,
    encrypted_key TEXT NOT NULL,
    label TEXT DEFAULT '',
    is_default INTEGER DEFAULT 0,
    last_used_at REAL,
    created_at REAL NOT NULL
);

-- 成本记录
CREATE TABLE IF NOT EXISTS cost_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT DEFAULT '',
    agent_id TEXT DEFAULT '',
    model TEXT NOT NULL,
    vendor TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    mode TEXT DEFAULT '',
    created_at REAL NOT NULL
);

-- 回测追踪
CREATE TABLE IF NOT EXISTS backtest_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT UNIQUE NOT NULL,
    symbol TEXT NOT NULL,
    stock_name TEXT DEFAULT '',
    signal TEXT NOT NULL,
    confidence INTEGER DEFAULT 0,
    price_at_decision REAL DEFAULT 0,
    agent_signals TEXT DEFAULT '{}',
    invalid_if TEXT DEFAULT '',
    price_3d REAL DEFAULT 0,
    price_5d REAL DEFAULT 0,
    price_10d REAL DEFAULT 0,
    price_20d REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    invalid_triggered INTEGER DEFAULT 0,
    evaluated INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- 观察列表
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT DEFAULT '',
    alert_conditions TEXT DEFAULT '{}',
    added_at REAL NOT NULL,
    UNIQUE(symbol)
);

-- 告警记录
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    message TEXT NOT NULL,
    severity TEXT DEFAULT 'info',
    acknowledged INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_tool_calls_conversation ON tool_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_agent ON tool_calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks(status);
CREATE INDEX IF NOT EXISTS idx_cost_records_created ON cost_records(created_at);
CREATE INDEX IF NOT EXISTS idx_cost_records_model ON cost_records(model);
CREATE INDEX IF NOT EXISTS idx_backtest_symbol ON backtest_tracking(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id);
"""


def upgrade_schema(conn) -> List[str]:
    """执行 Schema 升级，返回新增的表名列表"""
    new_tables = []
    try:
        # 获取现有表
        existing = set()
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for row in rows:
            existing.add(row[0])

        # 执行完整 Schema
        conn.executescript(FULL_SCHEMA)

        # 获取升级后的表
        after = set()
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for row in rows:
            after.add(row[0])

        new_tables = list(after - existing)
        if new_tables:
            logger.info(f"Schema 升级完成，新增 {len(new_tables)} 张表: {new_tables}")

    except Exception as e:
        logger.error(f"Schema 升级失败: {e}")

    return new_tables


def get_table_count(conn) -> int:
    """获取当前数据库表数量"""
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return len(rows)


def get_all_tables(conn) -> List[str]:
    """获取所有表名"""
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [row[0] for row in rows]
