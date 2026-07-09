# 研策中枢 AlphaScope v1.7.3

发布日期：2026-06-05

v1.7.3 是面向最终交付的 K 线体验补丁，修复股票工作台中 `分时 / 日K / 周K / 月K` 与底部横轴日期粒度不一致的问题。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.7.3.exe`
- 便携版：`AlphaScope-portable.zip`

## 修复

- 分时 K 线兜底数据改为 5 分钟间隔，横轴显示交易时间 `HH:mm`。
- 日K、周K 横轴显示 `MM-DD`。
- 月K 横轴显示 `YYYY-MM`。
- Workbench 主图和成交量图共用当前周期格式化逻辑，避免两个图的时间粒度不一致。
- 横轴按交易周期等距显示，周末和节假日不补空柱，因此相邻标签的自然日跨度可能不同。

## 验证

```bash
cd apps/web
npm run lint
npm run build
```

Browser-Use 实测：

- `分时`：横轴显示 `13:01`、`13:09`、`13:17` ... `15:00`。
- `日K`：横轴显示 `01-27` ... `05-29`。
- `周K`：横轴显示周线日期，如 `06-30`、`09-22`、`12-22`。
- `月K`：横轴显示 `2023-08` ... `2026-05`。
- 临时验证页 fresh console `warn/error=0`。

## 一键启动

下载 `AlphaScope-portable.zip` 解压后双击 `AlphaScope.exe` 即可启动；首次运行会自动创建 `.env`，需要使用 AI 分析时再填写模型 API Key。
