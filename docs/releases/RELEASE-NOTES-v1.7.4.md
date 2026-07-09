# 研策中枢 AlphaScope v1.7.4

发布日期：2026-06-05

v1.7.4 增强股票工作台 K 线周期：新增真正的年K，并提供自定义周期选择。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.7.4.exe`
- 便携版：`AlphaScope-portable.zip`

## 新增

- `年K`：前端请求 `frequency=1y`，后端从日线按自然年聚合 OHLC、成交量和成交额。
- `自定义`：可选择 `分时 / 日K / 周K / 月K / 年K` 粒度，并按粒度选择窗口大小。
- 年K横轴显示年份，月K横轴仍显示月份；月K标签抽样只是为了避免拥挤，不再被当作半年K。

## 验证

```bash
cd apps/web
npm run lint
npm run build

python -m pytest tests/test_price_periods.py tests/test_price_store.py -q
python -m ruff check backend/api/prices.py backend/price_periods.py tests/test_price_periods.py --output-format=github
python -m ruff format --check backend/api/prices.py backend/price_periods.py tests/test_price_periods.py
```

Browser-Use 实测：

- `年K`：横轴显示 `2024 / 2025 / 2026`。
- `自定义`：入口出现粒度和窗口两个选择器。
- `自定义年K + 10年`：横轴显示年度刻度，页面 fresh `warn/error=0`。

## 一键启动

下载 `AlphaScope-portable.zip` 解压后双击 `AlphaScope.exe` 即可启动；首次运行会自动创建 `.env`，需要使用 AI 分析时再填写模型 API Key。
