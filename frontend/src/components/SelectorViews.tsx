import type { SelectorMap, SelectorSweep } from '../api/types';
import { algoColor } from '../lib/colors';

export interface Band {
  id: string;
  start: number;
  end: number;
}

/** Run-length encode a sweep into coloured bands; the boundaries are the switch points. */
export function sweepBands(values: number[], choices: string[]): Band[] {
  const bands: Band[] = [];
  for (let i = 0; i < Math.min(values.length, choices.length); i++) {
    const last = bands[bands.length - 1];
    if (last && last.id === choices[i]) last.end = values[i];
    else bands.push({ id: choices[i], start: values[i], end: values[i] });
  }
  return bands;
}

export function switchPoints(bands: Band[]): number[] {
  return bands.slice(1).map((b) => b.start);
}

/** One strip per slider: which algorithm the selector picks across 0–100 with the others held fixed. */
export function SweepStrip(props: { sweep: SelectorSweep; label: string; current: number; allIds: string[] }) {
  const { sweep } = props;
  const bands = sweepBands(sweep.values, sweep.choices);
  const sw = switchPoints(bands);
  const W = 1010;
  const H = 58;
  const x = (v: number) => 5 + v * 10;
  const legend = sweep.legend ?? {};
  const desc = `${props.label}: ${bands.map((b) => `${legend[b.id] ?? b.id} from ${b.start} to ${b.end}`).join('; ')}. ${sw.length ? `Switch points at ${sw.join(', ')}.` : 'No switch.'} Current value ${props.current}.`;
  return (
    <figure style={{ margin: '0 0 10px' }} data-testid={`sweep-${sweep.slider}`}>
      <figcaption className="small" style={{ fontWeight: 600 }}>
        {props.label} <span className="muted">(current {props.current})</span>
      </figcaption>
      <svg className="strip-svg" viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={desc} preserveAspectRatio="none">
        {bands.map((b, i) => (
          <rect key={i} data-band={b.id} x={x(b.start)} y={4} width={x(b.end + 1) - x(b.start)} height={22} fill={algoColor(b.id, props.allIds)} stroke="var(--bg-panel)" strokeWidth={1}>
            <title>{`${legend[b.id] ?? b.id}: ${b.start}–${b.end}`}</title>
          </rect>
        ))}
        {sw.map((s) => (
          <line key={s} data-switch={s} x1={x(s)} x2={x(s)} y1={0} y2={30} stroke="var(--text)" strokeWidth={2} />
        ))}
        <path data-current={props.current} d={`M${x(props.current + 0.5) - 6},${42} L${x(props.current + 0.5) + 6},${42} L${x(props.current + 0.5)},${29} Z`} fill="var(--text)">
          <title>{`current value ${props.current}`}</title>
        </path>
        {[0, 25, 50, 75, 100].map((t) => (
          <text key={t} x={x(t)} y={H - 4} fontSize={10} textAnchor={t === 0 ? 'start' : t === 100 ? 'end' : 'middle'}>
            {t}
          </text>
        ))}
      </svg>
      <div className="small muted">
        {bands.map((b, i) => (
          <span key={i} style={{ marginRight: 10 }}>
            <span className="swatch" style={{ display: 'inline-block', background: algoColor(b.id, props.allIds), marginRight: 4 }} />
            {legend[b.id] ?? b.id} {b.start}–{b.end}
          </span>
        ))}
        {sw.length ? <span>· switch at {sw.join(', ')}</span> : null}
      </div>
    </figure>
  );
}

export function normaliseMap(raw: SelectorMap | string[][] | null | undefined, x: string, y: string): SelectorMap | null {
  if (!raw) return null;
  if (Array.isArray(raw)) return { x, y, n: raw.length, grid: raw };
  const r = raw as SelectorMap & { choices?: string[][] };
  const grid = r.grid ?? r.choices;
  if (!grid) return null;
  return { ...r, grid, n: r.n ?? grid.length };
}

/** Two-slider heat map of the selector's choice on an n × n grid; current point marked. */
export function SelectorHeatmap(props: { map: SelectorMap; xLabel: string; yLabel: string; xVal: number; yVal: number; allIds: string[]; legend: Record<string, string> }) {
  const n = props.map.grid.length;
  const cell = Math.max(4, Math.floor(328 / n));
  const size = cell * n;
  const pos = (v: number) => (v / 100) * (size - cell) + cell / 2;
  const ids = [...new Set(props.map.grid.flat())];
  return (
    <figure style={{ margin: 0 }} data-testid="selector-heatmap">
      <svg width={size + 50} height={size + 40} role="img" aria-label={`Selector choice over ${props.xLabel} (x) and ${props.yLabel} (y); ${ids.length} algorithms appear. Current point ${props.xVal}, ${props.yVal}.`}>
        <g transform="translate(40,4)">
          {props.map.grid.map((row, j) =>
            row.map((id, i) => <rect key={`${i}-${j}`} x={i * cell} y={(n - 1 - j) * cell} width={cell} height={cell} fill={algoColor(id, props.allIds)} />),
          )}
          <circle cx={pos(props.xVal)} cy={size - pos(props.yVal)} r={5} fill="none" stroke="var(--text)" strokeWidth={2} />
          <rect x={0} y={0} width={size} height={size} fill="none" stroke="var(--border)" />
          <text x={size / 2} y={size + 16} fontSize={11} textAnchor="middle" fill="var(--text)">
            {props.xLabel} 0 → 100
          </text>
          <text x={-30} y={size / 2} fontSize={11} textAnchor="middle" fill="var(--text)" transform={`rotate(-90, -30, ${size / 2})`}>
            {props.yLabel} 0 → 100
          </text>
        </g>
      </svg>
      <figcaption className="small">
        {ids.map((id) => (
          <span key={id} style={{ marginRight: 10 }}>
            <span className="swatch" style={{ display: 'inline-block', background: algoColor(id, props.allIds), marginRight: 4 }} />
            {props.legend[id] ?? id}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
