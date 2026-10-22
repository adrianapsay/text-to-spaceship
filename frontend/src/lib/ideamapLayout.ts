import type { IdeaEdge, IdeaMap, IdeaNode } from '../api/types';

export interface PlacedNode extends IdeaNode {
  col: number;
  row: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PlacedEdge extends IdeaEdge {
  path: string;
  mid: [number, number];
}

export interface IdeaLayout {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  width: number;
  height: number;
  columns: string[][];
}

const KIND_RANK: Record<string, number> = {
  parts: 0,
  part: 0,
  part_group: 0,
  proxy: 1,
  proxies: 1,
  algorithm: 2,
  candidate_algorithm: 2,
  weights: 3,
  priorities: 3,
  constraints: 4,
  constraint: 4,
  mode: 4,
  selected: 5,
  choice: 5,
  layout: 6,
  result: 6,
};

/**
 * Deterministic layered layout: longest-path layering on the DAG (back edges of cycles ignored, DFS in id
 * order), then one barycentre pass to order each column, ties broken by id. Same input → same picture.
 */
export function layoutIdeaMap(map: IdeaMap, opts: { colW?: number; rowH?: number; nodeW?: number; nodeH?: number } = {}): IdeaLayout {
  const colW = opts.colW ?? 340;
  const rowH = opts.rowH ?? 64;
  const nodeW = opts.nodeW ?? 200;
  const nodeH = opts.nodeH ?? 44;
  const ids = [...new Set(map.nodes.map((n) => n.id))].sort();
  const byId = new Map(map.nodes.map((n) => [n.id, n]));
  const out = new Map<string, string[]>();
  const inc = new Map<string, string[]>();
  for (const id of ids) {
    out.set(id, []);
    inc.set(id, []);
  }
  const edges = map.edges.filter((e) => byId.has(e.from) && byId.has(e.to) && e.from !== e.to);
  // drop back edges (cycle guard) with a deterministic DFS that starts from the earliest kinds
  // (parts → proxies → algorithms → priorities → constraints → choice → layout), so a cycle is cut at its
  // "backward" edge; unknown kinds sit in the middle
  const rank = (id: string) => KIND_RANK[byId.get(id)!.kind] ?? 3.5;
  ids.sort((a, b) => rank(a) - rank(b) || (a < b ? -1 : 1));
  const state = new Map<string, 0 | 1 | 2>();
  const keep = new Set<IdeaEdge>();
  const sortedEdges = [...edges].sort((a, b) => rank(a.to) - rank(b.to) || (a.from + a.to < b.from + b.to ? -1 : 1));
  const adj = new Map<string, IdeaEdge[]>();
  for (const e of sortedEdges) adj.set(e.from, [...(adj.get(e.from) ?? []), e]);
  const visit = (u: string) => {
    state.set(u, 1);
    for (const e of adj.get(u) ?? []) {
      const s = state.get(e.to) ?? 0;
      if (s === 1) continue; // back edge
      keep.add(e);
      if (s === 0) visit(e.to);
    }
    state.set(u, 2);
  };
  for (const id of ids) if (!state.get(id)) visit(id);
  for (const e of sortedEdges) {
    if (!keep.has(e)) continue;
    out.get(e.from)!.push(e.to);
    inc.get(e.to)!.push(e.from);
  }
  const layer = new Map<string, number>();
  const depth = (id: string): number => {
    if (layer.has(id)) return layer.get(id)!;
    const preds = inc.get(id)!;
    const d = preds.length ? Math.max(...preds.map(depth)) + 1 : 0;
    layer.set(id, d);
    return d;
  };
  ids.forEach(depth);
  const nCols = Math.max(0, ...layer.values()) + 1;
  const columns: string[][] = Array.from({ length: nCols }, () => []);
  for (const id of ids) columns[layer.get(id)!].push(id);
  // order: first column by kind then id; later columns by barycentre of predecessors
  const rowOf = new Map<string, number>();
  columns.forEach((col, c) => {
    if (c === 0) col.sort((a, b) => (byId.get(a)!.kind + a < byId.get(b)!.kind + b ? -1 : 1));
    else
      col.sort((a, b) => {
        const bc = (id: string) => {
          const p = inc.get(id)!.filter((x) => rowOf.has(x));
          return p.length ? p.reduce((s, x) => s + rowOf.get(x)!, 0) / p.length : Infinity;
        };
        const d = bc(a) - bc(b);
        return d !== 0 && Number.isFinite(d) ? d : a < b ? -1 : 1;
      });
    col.forEach((id, r) => rowOf.set(id, r));
  });
  const maxRows = Math.max(1, ...columns.map((c) => c.length));
  const nodes: PlacedNode[] = [];
  columns.forEach((col, c) =>
    col.forEach((id, r) => {
      const offset = ((maxRows - col.length) * rowH) / 2;
      nodes.push({ ...byId.get(id)!, col: c, row: r, x: 10 + c * colW, y: 10 + offset + r * rowH, w: nodeW, h: nodeH });
    }),
  );
  const pos = new Map(nodes.map((n) => [n.id, n]));
  const placedEdges: PlacedEdge[] = edges.map((e) => {
    const a = pos.get(e.from)!;
    const b = pos.get(e.to)!;
    const x1 = a.x + a.w;
    const y1 = a.y + a.h / 2;
    const x2 = b.x;
    const y2 = b.y + b.h / 2;
    const forward = x2 > x1;
    const path = forward
      ? `M${x1},${y1} C${x1 + 30},${y1} ${x2 - 30},${y2} ${x2},${y2}`
      : `M${a.x + a.w / 2},${a.y + a.h} C${a.x + a.w / 2},${a.y + a.h + 40} ${b.x + b.w / 2},${b.y + b.h + 40} ${b.x + b.w / 2},${b.y + b.h}`;
    return { ...e, path, mid: forward ? [(x1 + x2) / 2, (y1 + y2) / 2 - 4] : [(a.x + b.x) / 2 + a.w / 2, Math.max(a.y, b.y) + a.h + 34] };
  });
  return { nodes, edges: placedEdges, width: 20 + nCols * colW, height: 20 + maxRows * rowH + 30, columns };
}

/** Next node for keyboard navigation in the idea map. */
export function navigate(layout: IdeaLayout, current: string, key: string): string {
  const cur = layout.nodes.find((n) => n.id === current);
  if (!cur) return layout.nodes[0]?.id ?? current;
  const col = layout.columns[cur.col];
  if (key === 'ArrowDown') return col[Math.min(col.length - 1, cur.row + 1)];
  if (key === 'ArrowUp') return col[Math.max(0, cur.row - 1)];
  if (key === 'Home') return layout.nodes[0]?.id ?? current;
  if (key === 'End') return layout.nodes[layout.nodes.length - 1]?.id ?? current;
  if (key === 'ArrowRight' || key === 'ArrowLeft') {
    const linked = layout.edges
      .filter((e) => (key === 'ArrowRight' ? e.from === current : e.to === current))
      .map((e) => (key === 'ArrowRight' ? e.to : e.from))
      .sort();
    if (linked.length) return linked[0];
    const next = layout.columns[cur.col + (key === 'ArrowRight' ? 1 : -1)];
    if (!next?.length) return current;
    return next[Math.min(next.length - 1, cur.row)];
  }
  return current;
}

const TAB_ALIASES: Record<string, string> = {
  overview: 'overview',
  components: 'components',
  component: 'components',
  optimization: 'optimization',
  optimisation: 'optimization',
  physics: 'physics',
  comparison: 'comparison',
  'algorithm comparison': 'comparison',
  algorithm_comparison: 'comparison',
  size: 'size',
  'size study': 'size',
  size_study: 'size',
  explain: 'explain',
  engineering: 'engineering',
  'engineering constraints': 'engineering',
  engineering_constraints: 'engineering',
  manufacturable: 'manufacturable',
  'manufacturable design': 'manufacturable',
  manufacturable_design: 'manufacturable',
  mfg: 'manufacturable',
  cad: 'cad',
  'cad validation': 'cad',
  cad_validation: 'cad',
  results: 'results',
  'results & export': 'results',
  results_export: 'results',
  export: 'results',
};

export function tabFromName(name: string | null | undefined): string | null {
  if (!name) return null;
  return TAB_ALIASES[name.trim().toLowerCase()] ?? null;
}
