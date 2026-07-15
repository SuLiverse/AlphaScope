export interface EvidenceGraphPoint {
  id: string;
  x: number;
  y: number;
  label: string;
  color: string;
}

export interface EvidenceGraphLayout {
  points: EvidenceGraphPoint[];
  edges: Array<Record<string, unknown>>;
  width: number;
  height: number;
  truncated: number;
}

export function buildEvidenceGraphLayout(
  nodes: Array<Record<string, unknown>>,
  edges: Array<Record<string, unknown>>,
  limit = 50,
): EvidenceGraphLayout {
  const visible = (nodes || []).slice(0, Math.max(0, limit));
  if (!visible.length) {
    return { points: [], edges: [], width: 560, height: 180, truncated: 0 };
  }

  const columns = Math.min(8, visible.length);
  const columnWidth = 104;
  const rowHeight = 68;
  const points = visible.map((node, index) => ({
    id: String(node.id ?? `n${index}`),
    x: 52 + (index % columns) * columnWidth,
    y: 28 + Math.floor(index / columns) * rowHeight,
    label: String(node.label || node.id || index).slice(0, 10),
    color: String(node.color || '#6366f1'),
  }));
  const visibleIds = new Set(points.map((point) => point.id));
  const visibleEdges = (edges || []).filter((edge) => {
    const source = String(edge.source ?? edge.from ?? '');
    const target = String(edge.target ?? edge.to ?? '');
    return visibleIds.has(source) && visibleIds.has(target);
  });
  const rows = Math.ceil(visible.length / columns);

  return {
    points,
    edges: visibleEdges,
    width: Math.max(560, columns * columnWidth),
    height: Math.max(180, rows * rowHeight + 24),
    truncated: Math.max(0, (nodes?.length || 0) - visible.length),
  };
}
