import { describe, expect, it } from 'vitest';
import { getCitationDisplayState, getQuantRefereeDisplayState } from './reviewStatus';

describe('review result presentation', () => {
  it('does not present insufficient quant referee data as a completed result', () => {
    const state = getQuantRefereeDisplayState({
      status: 'insufficient',
      symbol: '600519',
      stance: '未知',
      net_score: 0,
      signals: [],
      n_bull: 0,
      n_bear: 0,
      n_neutral: 0,
      llm_alignment: '',
    });
    expect(state.tone).toBe('skipped');
    expect(state.label).toContain('不足');
  });

  it.each(['skipped', 'error', 'unknown'])('keeps citation status %s non-healthy', (status) => {
    const state = getCitationDisplayState({
      status,
      n_claims: 0,
      n_verified: 0,
      n_unverified: 0,
      n_citation_ok: 0,
      n_citation_bad: 0,
      grounding_score: 0,
    });
    expect(state.tone).not.toBe('ok');
    expect(state.fallback).not.toContain('未发现明显');
  });
});
