import { describe, expect, it } from 'vitest';
import { formatPercent } from './backtestFormat';

describe('formatPercent', () => {
  it('formats backend percentage points without multiplying again', () => {
    expect(formatPercent(0.5)).toBe('+0.50%');
    expect(formatPercent(50)).toBe('+50.00%');
    expect(formatPercent(-12.345)).toBe('-12.35%');
  });
});
