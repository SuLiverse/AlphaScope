// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { fetchApi } from '../lib/api';
import { normalizeAnalysisResult } from '../lib/analysisAdapter';
import { ReportCharts } from './ReportCharts';

vi.mock('../lib/api', () => ({ fetchApi: vi.fn() }));
vi.mock('recharts', async importOriginal => {
  const original = await importOriginal<Record<string, unknown>>();
  return { ...original, ResponsiveContainer: () => null };
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('never retrieves current market data for an archived research version', () => {
  render(<ReportCharts symbol="600519" result={normalizeAnalysisResult({
    agents: {}, research_version_id: 'v1',
    chart_snapshot: { prices: [{ date: '2026-06-30', close: 10 }], factors: { rsi: 42 } },
  })} />);
  expect(fetchApi).not.toHaveBeenCalled();
  expect(screen.getByText(/已保存的研究快照/)).toBeTruthy();
});

it('does not fill a legacy historical report with current data when its snapshot is absent', () => {
  render(<ReportCharts symbol="600519" result={normalizeAnalysisResult({
    agents: {}, research_snapshot: { cutoff_enforced: true, effective_as_of: '2026-06-30' },
  })} />);
  expect(fetchApi).not.toHaveBeenCalled();
  expect(screen.getByText('未存档')).toBeTruthy();
});
