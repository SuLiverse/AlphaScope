import { describe, expect, it } from 'vitest';
import { buildEvidenceGraphLayout } from './evidenceGraph';

describe('buildEvidenceGraphLayout', () => {
  it('keeps fifty nodes on stable non-overlapping grid positions', () => {
    const nodes = Array.from({ length: 50 }, (_, index) => ({ id: `n${index}`, label: `Node ${index}` }));
    const layout = buildEvidenceGraphLayout(nodes, []);
    const positions = new Set(layout.points.map((point) => `${point.x}:${point.y}`));

    expect(layout.points).toHaveLength(50);
    expect(positions.size).toBe(50);
    expect(layout.height).toBeGreaterThan(400);
  });

  it('limits oversized graphs and removes edges to hidden nodes', () => {
    const nodes = Array.from({ length: 55 }, (_, index) => ({ id: `n${index}` }));
    const layout = buildEvidenceGraphLayout(nodes, [
      { source: 'n0', target: 'n1' },
      { source: 'n0', target: 'n54' },
    ]);

    expect(layout.points).toHaveLength(50);
    expect(layout.truncated).toBe(5);
    expect(layout.edges).toEqual([{ source: 'n0', target: 'n1' }]);
  });
});
