// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { normalizeAnalysisResult } from '../../lib/analysisAdapter';
import { ResearchStatusStrip } from './ResearchStatusStrip';
import { ResearchComparison } from './ResearchComparison';
import { DataIntegrityBanner } from './DataIntegrityBanner';
import type { VersionComparison } from '../../lib/researchWorkspace';

afterEach(cleanup);

describe('Research presentation', () => {
  it('keeps acquisition, evidence metadata and human review counts independent', () => {
    const result = normalizeAnalysisResult({ agents: {}, evidence_pool: [
      { number: 1, evidence_id: 'e1', source: '公告', published_at: '2026-06-30' },
      { number: 2, evidence_id: 'e2' },
    ] });
    render(<><ResearchStatusStrip result={result} progress={{ reviewed: 1, total: 5 }} /><DataIntegrityBanner result={result} /></>);
    expect(screen.getByText('状态未记录')).toBeTruthy();
    expect(screen.getByText('2 条已保存')).toBeTruthy();
    expect(screen.getByText('来源 1/2 · 日期 1/2')).toBeTruthy();
    expect(screen.getByText('1/5 条已复核')).toBeTruthy();
    expect(screen.queryByText(/完整、健康/)).toBeNull();
    expect(screen.getByText(/无法确认采集是否完整/)).toBeTruthy();
  });

  it('surfaces changed sections first and labels structured model fields', () => {
    const comparison: VersionComparison = {
      summary: '已记录模型字段有变化', warnings: ['至少一个版本缺少完整的已解析模型配置'],
      conclusion: { before: { final: '积极' }, after: { final: '谨慎' }, changed: true },
      context: [], metrics: [], agents: [],
      evidence: [{ field: 'e1', before: null, after: { source: '半年报', published_at: '2026-06-30', source_url: 'javascript:alert(1)', excerpt: '原始证据内容' }, status: 'added' }],
      models: [{ field: 'actual', before: { fundamental: { model: 'old-model' } }, after: { fundamental: { model: 'new-model' } }, status: 'changed' }],
    };
    render(<ResearchComparison comparison={comparison} />);
    expect(screen.queryByRole('heading', { name: '指标 (0)' })).toBeNull();
    expect(screen.getByText('模型配置 (1)').closest('details')?.open).toBe(false);
    fireEvent.click(screen.getByLabelText('显示无差异分组'));
    expect(screen.getByRole('heading', { name: '指标 (0)' })).toBeTruthy();
    expect(screen.getByText('实际使用')).toBeTruthy();
    expect(screen.getByText('基本面：模型：new-model')).toBeTruthy();
    expect(screen.getByText('原始证据内容')).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('至少一个版本缺少完整的已解析模型配置')).toBeTruthy();
  });
});
