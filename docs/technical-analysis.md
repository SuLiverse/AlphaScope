# 技术面分析

v0.52 新增功能。后端技术指标计算引擎，供 Agent 和 API 使用。

## 指标列表

| 指标 | 函数 | 说明 |
|------|------|------|
| 均线 MA | `calc_ma(bars, periods)` | 简单移动均线（5/10/20/60） |
| MACD | `calc_macd(bars, fast, slow, signal)` | DIF/DEA/MACD 柱 |
| RSI | `calc_rsi(bars, period)` | 相对强弱指标（14） |
| KDJ | `calc_kdj(bars, n, m1, m2)` | 随机指标（9,3,3） |
| 量比 | `calc_volume_ratio(bars, period)` | 当日量 / N日均量 |
| 支撑压力 | `calc_support_resistance(bars, lookback)` | 枢轴点 + 摆动高低点 |
| ATR | `calc_atr(bars, period=20)` | 真实波幅均值；不足 period 为 0 |
| 唐奇安 | `calc_donchian(bars, period=20)` | 上轨/下轨/宽度；**通道不含当日** |
| 综合 | `calc_all(bars)` | 一次性计算所有指标 |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/technical/{symbol}` | 所有指标 |
| GET | `/api/technical/{symbol}/ma` | 均线 |
| GET | `/api/technical/{symbol}/macd` | MACD |
| GET | `/api/technical/{symbol}/rsi` | RSI |
| GET | `/api/technical/{symbol}/kdj` | KDJ |
| GET | `/api/technical/{symbol}/support-resistance` | 支撑压力 |
| POST | `/api/quant/chanlun` | 缠论结构标注（分型/笔/中枢/背驰） |

## 使用示例

### 计算所有指标

```bash
curl http://localhost:8000/api/technical/600519
```

返回：
```json
{
  "success": true,
  "data": {
    "summary": {
      "symbol": "600519",
      "date": "2025-05-20",
      "close": 1800.0,
      "ma5": 1790.0,
      "ma20": 1750.0,
      "dif": 12.5,
      "dea": 10.2,
      "macd": 4.6,
      "rsi": 65.3,
      "k": 72.1,
      "d": 68.5,
      "j": 79.3,
      "volume_ratio": 1.2
    },
    "bars": [...],
    "support_resistance": {
      "pivot": 1790.0,
      "support": [1780.0, 1770.0],
      "resistance": [1800.0, 1810.0],
      "swing_highs": [1820.0],
      "swing_lows": [1740.0]
    }
  }
}
```

## 计算逻辑

### MACD
- DIF = EMA(12) - EMA(26)
- DEA = EMA(DIF, 9)
- MACD柱 = (DIF - DEA) × 2

### RSI
- RSI = 100 - 100 / (1 + RS)
- RS = 平均涨幅 / 平均跌幅（14日）

### KDJ
- RSV = (Close - Low_N) / (High_N - Low_N) × 100
- K = 2/3 × K_prev + 1/3 × RSV
- D = 2/3 × D_prev + 1/3 × K
- J = 3K - 2D

### 支撑压力
- 枢轴点 = (High + Low + Close) / 3
- S1 = 2×Pivot - High, R1 = 2×Pivot - Low
- 摆动高低点：局部极值（前后各 2 根 K 线）

### ATR
- TR = max(H−L, |H−PDC|, |L−PDC|)
- ATR(period) = 近 period 根 TR 的简单平均（含当日）
- 因子 `atr_20` = ATR(20) / close，单位 %，方向中性

### 唐奇安通道
- 上轨 / 下轨取 **当日之前** period 根的最高价 / 最低价，当日高低不进入通道
- 宽度 = 上轨 − 下轨；因子 `donchian_width_20` = 宽度 / close
- 海龟策略入场通道同样不含当日；可选 ATR 止损的 N 用不含当日的 TR 均值

### 缠论结构 API
`POST /api/quant/chanlun`，请求体与 `POST /api/quant/patterns` 同形：`symbol` / `start_date` / `end_date` / `lookback`。

返回分型、笔、中枢、背驰标注和可选的一/二/三类点 **标注**（`signals[].type` 如 `buy3`，不是下单指令）。中枢必须至少三段重叠；两笔有交集不成中枢。`disclaimer` 写明：描述历史走势结构，不预测、不构成买卖建议。
