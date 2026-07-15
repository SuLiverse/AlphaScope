import { describe, expect, it } from 'vitest';
import { normalizeParamSweepResult } from './integrationContracts';

describe('normalizeParamSweepResult', () => {
  it('normalizes the stable mapping contract', () => {
    const result = normalizeParamSweepResult({
      status: 'ok',
      engine: 'vectorbt',
      symbol: '600519',
      metric: 'sharpe',
      n_trials: 6,
      returned: 1,
      results: [
        {
          params: { fast: 5, slow: 30 },
          metrics: {
            sharpe: 1.2,
            probabilistic_sharpe: 0.91,
            deflated_sharpe: 0.72,
            n_trials_for_dsr: 6,
          },
          observations: 249,
          selection_bias_status: 'ok',
        },
      ],
      disclaimer: 'research only',
    });

    expect(result.status).toBe('ok');
    expect(result.n_trials).toBe(6);
    expect(result.results[0].deflated_sharpe).toBe(0.72);
    expect(result.results[0].observations).toBe(249);
  });

  it('keeps compatibility with a legacy list but does not claim unknown statistics are healthy', () => {
    const result = normalizeParamSweepResult([
      {
        params: { fast: 5, slow: 20 },
        metrics: { sharpe: 1, probabilistic_sharpe: 0.8, deflated_sharpe: 0.6 },
      },
    ]);

    expect(result.status).toBe('degraded');
    expect(result.returned).toBe(1);
    expect(result.results[0].probabilistic_sharpe).toBe(0.8);
  });

  it('preserves missing probabilities as null for insufficient samples', () => {
    const result = normalizeParamSweepResult({
      status: 'ok',
      results: [{
        params: { fast: 5, slow: 20 },
        metrics: { sharpe: null, probabilistic_sharpe: null, deflated_sharpe: null },
        observations: 1,
        selection_bias_status: 'insufficient',
      }],
    });

    expect(result.status).toBe('degraded');
    expect(result.results[0].probabilistic_sharpe).toBeNull();
    expect(result.results[0].deflated_sharpe).toBeNull();
  });
});
