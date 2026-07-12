import { describe, expect, it } from 'vitest';

import { normalizeAnalysisResult } from './analysisAdapter';

describe('normalizeAnalysisResult research trust contract', () => {
  it('keeps trust metrics and evidence backlinks from nested API results', () => {
    const result = normalizeAnalysisResult({
      result: {
        agents: {
          fundamental: {
            signal: '买入',
            confidence: 78,
            reason: '公告与财务数据一致',
            evidence_ids: ['ev-1'],
          },
        },
        evidence_pool: [
          {
            number: 1,
            evidence_id: 'ev-1',
            doc_type: 'announcement',
            source: 'cninfo',
            published_at: '2026-07-10',
            preview: '业绩公告',
          },
        ],
        research_trust: {
          score: 86,
          grade: 'high',
          label: '高可信',
          evidence_count: 3,
          source_count: 3,
          metrics: {
            coverage: 1,
            source_completeness: 1,
            date_completeness: 1,
            freshness: 0.9,
            source_quality: 0.85,
            source_diversity: 1,
          },
          penalties: { contradictions: 0, missing_evidence: 0 },
          warnings: [],
        },
        research_snapshot: {
          snapshot_id: 'abc123',
          requested_as_of: '2026-07-10',
          effective_as_of: '2026-07-10',
          cutoff_enforced: true,
          price_data_date: '2026-07-10',
          latest_evidence_date: '2026-07-09',
          evidence_count: 3,
          undated_evidence_count: 0,
          research_question: '利润增长是否可持续？',
          warnings: [],
        },
      },
    });

    expect(result.research_trust?.score).toBe(86);
    expect(result.research_trust?.metrics.freshness).toBe(0.9);
    expect(result.evidence_pool?.[0].source).toBe('cninfo');
    expect(result.agents.fundamental.evidence_ids).toEqual(['ev-1']);
    expect(result.research_snapshot?.cutoff_enforced).toBe(true);
    expect(result.research_snapshot?.research_question).toBe('利润增长是否可持续？');
  });

  it('clamps malformed trust values instead of leaking schema drift to the UI', () => {
    const result = normalizeAnalysisResult({
      agents: {},
      research_trust: {
        score: 999,
        grade: 'unexpected',
        metrics: { coverage: -1, freshness: 4 },
        penalties: {},
        warnings: [{ code: 'x', message: '复核' }],
      },
    });

    expect(result.research_trust?.score).toBe(100);
    expect(result.research_trust?.grade).toBe('insufficient');
    expect(result.research_trust?.metrics.coverage).toBe(0);
    expect(result.research_trust?.metrics.freshness).toBe(1);
  });
});
