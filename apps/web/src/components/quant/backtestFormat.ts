/**
 * Backtesting 展示/解析纯函数。
 */
import { findStockTarget, type StockTarget } from "../../lib/stocks";

/** 把实验摘要(随 mode 不同)渲染成一行紧凑文本。 */
export function formatExpSummary(mode: string, summary?: Record<string, number | string>): string {
  if (!summary) return '--';
  const num = (v: unknown, d = 2) => (typeof v === 'number' ? v.toFixed(d) : '--');
  if (mode === 'backtest') {
    return `收益 ${num(summary.total_return)}% · 夏普 ${num(summary.sharpe_ratio)} · 回撤 ${num(summary.max_drawdown)}% · ${summary.trade_count ?? 0}笔`;
  }
  if (mode === 'walk_forward') {
    return `${summary.n_windows ?? 0}窗 · 样本外胜率 ${num(summary.pct_profitable_windows)}% · 一致性 ${num(summary.consistency_score)} · ${summary.robustness ?? ''}`;
  }
  if (mode === 'chip_distribution') {
    return `获利盘 ${num(summary.profit_ratio)}% · 均成本 ${num(summary.avg_cost)} · 90%集中度 ${num(summary.concentration_90)}%`;
  }
  if (mode === 'strategy_compare') {
    return `${summary.evaluated ?? 0}策略 · 冠军 ${summary.top_strategy ?? '--'}(${num(summary.top_total_return)}%) · 按${summary.rank_by ?? ''}`;
  }
  if (mode === 'evolution') {
    return `${summary.fitness_metric ?? ''} 最优 ${num(summary.best_fitness, 3)} · 较默认 ${num(summary.improvement, 3)} · ${summary.generations ?? 0}代×${summary.population_size ?? 0} · ${summary.evaluations ?? 0}评估`;
  }
  return Object.entries(summary).map(([k, v]) => `${k} ${typeof v === 'number' ? v.toFixed(2) : v}`).join(' · ');
}

export const DEFAULT_POOL_TEXT = `600519 贵州茅台
300750 宁德时代
600036 招商银行
002594 比亚迪
300059 东方财富
601318 中国平安`;

export function formatGenome(genome?: Record<string, number>): string {
  if (!genome || !Object.keys(genome).length) return '--';
  return Object.entries(genome)
    .map(([k, v]) => `${k}=${typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(3)) : v}`)
    .join(', ');
}

export function parsePoolText(value: string): StockTarget[] {
  const tokens = value
    .split(/[\n,，;\t ]+/)
    .map((item) => item.trim())
    .filter(Boolean);

  const seen = new Set<string>();
  return tokens.reduce<StockTarget[]>((acc, token) => {
    const stock = findStockTarget(token);
    if (stock && !seen.has(stock.symbol)) {
      seen.add(stock.symbol);
      acc.push(stock);
    }
    return acc;
  }, []);
}

export function formatFactor(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  return value.toFixed(2);
}

export function formatPercent(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}
