# AlphaScope MCP Server

把 AlphaScope 的研究能力通过 **MCP (Model Context Protocol)** 暴露给外部 LLM 客户端
(Claude Desktop、其他 MCP client),让外部 AI 能直接调用 AlphaScope 的行情 / 财务 /
证据 / 回测 / 集成中心能力。

> 合规:MCP server **只暴露研究 / 数据 / 回测工具**,显式禁止任何实盘下单工具
> (`submit_order` / `place_order` / `connect_live_broker` 等)。启动时由
> `assert_no_forbidden_tools()` 边界守卫断言,与项目 No-Live-Order 红线一致。

## 前置依赖

MCP 是可选依赖(import-guard 包裹,不装不影响其余功能):

```bash
pip install "mcp[cli]"
```

检查是否就绪:

```bash
# 后端 API
curl http://localhost:8000/api/diagnostics/mcp
# 或命令行
python -c "from backend.mcp_server import describe; print(describe())"
```

`available: true` 即可启动。

## 启动方式

### 1. console-script(推荐,`pip install` 后可直接用)

```bash
alphascope-mcp
```

### 2. 模块方式

```bash
python -m backend.mcp_server
```

server 默认走 **stdio 传输**,由外部 MCP client 拉起;不要在前台手动常驻运行。

## 接入 Claude Desktop

编辑 Claude Desktop 的配置文件(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`),
在 `mcpServers` 中加入:

```json
{
  "mcpServers": {
    "alphascope": {
      "command": "alphascope-mcp"
    }
  }
}
```

重启 Claude Desktop 后,即可在对话中调用 AlphaScope 暴露的研究工具(如查询行情、
检索证据链、列出集成中心 adapter、查看交易边界等)。

## 暴露的工具

`describe()["tools"]` 列出全部已注册工具,典型包括:

- `get_market_data` — 查询标的行情快照
- `search_evidence` — 检索投研证据链
- `list_integrations` — 列出集成注册中心 adapter(vectorbt / OpenBB / Qlib / TradingAgents)
- `get_trading_boundary` — 查看 No-Live-Order 交易边界
- `is_trading_day` — 判断是否为交易日

所有工具仅研究语义,输出附免责声明;**绝不**暴露订单/实盘能力。

## 边界守卫

`backend/mcp_server.py` 的 `FORBIDDEN_TOOL_NAMES` 列出永久禁止的工具名;
`assert_no_forbidden_tools()` 在每次启动前断言 server 未注册任何禁止工具,
违例直接拒绝启动。这保证「外部 LLM 经 MCP 调用 AlphaScope」也严格遵守合规红线。
