export interface ParamSweepRow {
  params: Record<string, string | number>;
  metrics: Record<string, number | null>;
  probabilistic_sharpe: number | null;
  deflated_sharpe: number | null;
  n_trials: number;
  observations: number;
  selection_bias_status: string;
}

export interface ParamSweepResult {
  status: 'ok' | 'degraded' | 'empty' | 'error';
  engine: string;
  symbol: string;
  metric: string;
  n_trials: number;
  returned: number;
  results: ParamSweepRow[];
  disclaimer: string;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asNumber(value: unknown): number | null {
  if (value == null || value === '' || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function normalizeParamSweepResult(value: unknown): ParamSweepResult {
  const root = asRecord(value);
  const rawRows = Array.isArray(value)
    ? value
    : Array.isArray(root.results)
      ? root.results
      : Array.isArray(root.top)
        ? root.top
        : [];
  const rootTrials = Math.max(1, Number(root.n_trials) || 1);
  const rows = rawRows
    .map(asRecord)
    .filter((row) => Object.keys(row).length > 0)
    .map((row): ParamSweepRow => {
      const metricsRaw = asRecord(row.metrics);
      const metrics: Record<string, number | null> = {};
      Object.entries(metricsRaw).forEach(([key, metricValue]) => {
        metrics[key] = asNumber(metricValue);
      });
      const probabilisticSharpe = asNumber(
        row.probabilistic_sharpe ?? metricsRaw.probabilistic_sharpe,
      );
      const deflatedSharpe = asNumber(row.deflated_sharpe ?? metricsRaw.deflated_sharpe);
      const rowTrials = Math.max(
        1,
        Number(row.n_trials ?? metricsRaw.n_trials_for_dsr ?? rootTrials) || rootTrials,
      );
      return {
        params: asRecord(row.params) as Record<string, string | number>,
        metrics,
        probabilistic_sharpe: probabilisticSharpe,
        deflated_sharpe: deflatedSharpe,
        n_trials: rowTrials,
        observations: Math.max(0, Number(row.observations) || 0),
        selection_bias_status: String(row.selection_bias_status || 'unknown'),
      };
    });
  const derivedStatus = rows.length
    ? rows.every((row) => row.selection_bias_status === 'ok') ? 'ok' : 'degraded'
    : 'empty';
  const statusValue = String(root.status || derivedStatus).toLowerCase();
  let status: ParamSweepResult['status'] = ['ok', 'degraded', 'empty', 'error'].includes(statusValue)
    ? statusValue as ParamSweepResult['status']
    : rows.length
      ? 'degraded'
      : 'empty';
  if (status === 'ok' && derivedStatus === 'degraded') status = 'degraded';

  return {
    status,
    engine: String(root.engine || 'vectorbt'),
    symbol: String(root.symbol || ''),
    metric: String(root.metric || 'sharpe'),
    n_trials: rootTrials,
    returned: Math.max(0, Number(root.returned) || rows.length),
    results: rows,
    disclaimer: String(root.disclaimer || ''),
  };
}
