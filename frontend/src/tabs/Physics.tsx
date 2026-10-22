import { useMemo } from 'react';
import type { Mat3, Vec3 } from '../api/types';
import { useApp } from '../store/store';
import { useDisplayMetrics } from '../hooks';
import { aggregate, productsOfInertia } from '../lib/physics';
import { fmt, fmtColumn, fmtVec } from '../lib/fmt';
import { EmptyState, MockTag, Panel, Notice, KV } from '../components/ui';

function Projection(props: { title: string; ax: [0 | 1 | 2, 0 | 1 | 2]; size: Vec3; box: Vec3; com: Vec3 | null; target: Vec3 }) {
  const [a, b] = props.ax;
  const names = ['x', 'y', 'z'];
  const W = 220;
  const H = 220;
  const ext = Math.max(props.size[a], props.size[b]) / 2 + 10;
  const sx = (v: number) => W / 2 + (v / ext) * (W / 2 - 14);
  const sy = (v: number) => H / 2 - (v / ext) * (H / 2 - 14);
  const rect = (hx: number, hy: number) => ({ x: sx(-hx), y: sy(hy), width: sx(hx) - sx(-hx), height: sy(-hy) - sy(hy) });
  const enc = rect(props.size[a] / 2, props.size[b] / 2);
  const cds = rect(props.box[a], props.box[b]);
  const inside = props.com ? Math.abs(props.com[a]) <= props.box[a] && Math.abs(props.com[b]) <= props.box[b] : null;
  return (
    <figure style={{ margin: 0 }}>
      <svg width={W} height={H} role="img" aria-label={`${props.title}: centre of mass ${props.com ? `at ${names[a]} ${props.com[a].toFixed(1)} mm, ${names[b]} ${props.com[b].toFixed(1)} mm, ${inside ? 'inside' : 'outside'} the CDS box` : 'not available'}`}>
        <rect {...enc} fill="none" stroke="var(--border)" />
        <rect {...cds} fill="none" stroke="var(--accent)" strokeDasharray="5 4" />
        <line x1={sx(props.target[a]) - 6} x2={sx(props.target[a]) + 6} y1={sy(props.target[b])} y2={sy(props.target[b])} stroke="var(--accent)" />
        <line x1={sx(props.target[a])} x2={sx(props.target[a])} y1={sy(props.target[b]) - 6} y2={sy(props.target[b]) + 6} stroke="var(--accent)" />
        {props.com ? (
          <g>
            <circle cx={sx(props.com[a])} cy={sy(props.com[b])} r={6} fill="var(--bg-panel)" stroke="var(--text)" strokeWidth={1.5} />
            <path d={`M${sx(props.com[a])},${sy(props.com[b])} l6,0 a6,6 0 0,1 -6,6 z M${sx(props.com[a])},${sy(props.com[b])} l-6,0 a6,6 0 0,1 6,-6 z`} fill="var(--text)" />
          </g>
        ) : null}
        <text x={6} y={14} fontSize={11} fill="var(--text-muted)">
          {names[b]} ↑
        </text>
        <text x={W - 30} y={H - 6} fontSize={11} fill="var(--text-muted)">
          {names[a]} →
        </text>
      </svg>
      <figcaption className="small">
        {props.title}: dashed = CDS box ±{props.box[a]} / ±{props.box[b]} mm{inside === null ? '' : inside ? ' — COM inside' : ' — COM outside'}
      </figcaption>
    </figure>
  );
}

function TensorTable(props: { M: Mat3; caption: string; testId?: string; names?: string[] }) {
  const col = fmtColumn(props.M.flat());
  const n = props.names ?? ['x', 'y', 'z'];
  return (
    <table className="data" style={{ width: 'auto' }} data-testid={props.testId}>
      <caption className="small muted" style={{ textAlign: 'left', captionSide: 'top' }}>
        {props.caption} {col.header}
      </caption>
      <thead>
        <tr>
          <th />
          {n.map((x) => (
            <th key={x} className="num">
              {x}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {props.M.map((row, i) => (
          <tr key={i}>
            <th>{n[i]}</th>
            {row.map((_, j) => (
              <td key={j} className="num">
                {col.cells[i * 3 + j]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PhysicsTab() {
  const dm = useDisplayMetrics();
  const parts = useApp((s) => s.dataset.parts);
  const rotations = useApp((s) => s.dataset.rotations);
  const project = useApp((s) => s.dataset.project);
  const settings = useApp((s) => s.goals.settings);
  const massEdits = useApp((s) => s.physical.massEdits);
  const m = dm.metrics;
  const layout = dm.layout;
  const size = (project?.enclosure.size_mm as Vec3 | undefined) ?? [100, 100, 340.5];
  const box = (project?.limits.com_box_mm as Vec3 | undefined) ?? [20, 20, 70];
  const target = settings?.target_com_mm ?? [0, 0, 0];
  const contrib = useMemo(() => {
    if (!layout || !rotations.length) return null;
    try {
      return aggregate(parts, layout.poses, rotations, Object.fromEntries(Object.entries(massEdits).map(([k, v]) => [k, v.mass_kg])));
    } catch {
      return null;
    }
  }, [layout, parts, rotations, massEdits]);
  if (!m || !layout) return <div className="tab-scroll"><EmptyState title="No validated layout yet">Physics is shown for the layout on screen.</EmptyState></div>;
  const I = (m.inertia_kgm2 as Mat3 | null) ?? null;
  const P = I ? productsOfInertia(I) : null;
  const pMat: Mat3 | null = P
    ? [
        [0, P.Pxy, P.Pxz],
        [P.Pxy, 0, P.Pyz],
        [P.Pxz, P.Pyz, 0],
      ]
    : null;
  const maxTerm = contrib ? Math.max(...contrib.contributions.map((c) => c.self_trace_kgm2 + c.parallel_trace_kgm2)) : 0;
  return (
    <div className="tab-scroll" data-testid="tab-physics">
      {dm.source === 'local' ? <Notice tone="info">Showing a local recompute after your mass edit; the backend confirmation is pending.</Notice> : null}
      <Panel title="Centre of mass vs the CDS box" caption={`layout ${layout.id} · COM ${fmtVec(m.com_mm as Vec3)} · ${settings?.stage === 2 ? 'HARD in Stage 2' : 'displayed, not enforced in Stage 1'}`} right={<MockTag />}>
        <div className="row" style={{ alignItems: 'flex-start', gap: 24 }}>
          <Projection title="Top (XY)" ax={[0, 1]} size={size} box={box} com={(m.com_mm as Vec3) ?? null} target={target} />
          <Projection title="Front (XZ)" ax={[0, 2]} size={size} box={box} com={(m.com_mm as Vec3) ?? null} target={target} />
          <Projection title="Side (YZ)" ax={[1, 2]} size={size} box={box} com={(m.com_mm as Vec3) ?? null} target={target} />
          <KV
            rows={[
              ['Balance error ‖C − C*‖', fmt(m.com_error_mm, 'mm')],
              ['Margin to CDS box (x, y, z)', fmtVec(m.com_box_margin_mm as Vec3)],
              ['Inside CDS box', m.com_box_ok == null ? '—' : m.com_box_ok ? 'yes' : 'no'],
              ['Total mass', fmt(m.mass_kg, 'kg')],
            ]}
          />
        </div>
      </Panel>
      <div className="grid-2">
        <Panel title="Inertia tensor about the COM" caption="I = ∫(‖r‖²E − r rᵀ) dm, so off-diagonal I_xy = −∫xy dm">
          {I ? <TensorTable M={I} caption="Inertia tensor I_C" testId="inertia-tensor" /> : <span className="muted">—</span>}
        </Panel>
        <Panel title="Products of inertia" caption="P_xy = ∫xy dm = −I_xy (separate table; a bare “Ixy” is never shown)">
          {pMat ? <TensorTable M={pMat} caption="Products P_ij (diagonal not defined, shown as 0)" testId="products-table" /> : <span className="muted">—</span>}
          <div className="small muted" style={{ marginTop: 4 }}>
            ‖P‖ = √(I_xy² + I_xz² + I_yz²) = {fmt(m.products_norm_kgm2, 'kgm2')} · κ = max|I_ij| / √(I_ii·I_jj) = {fmt(m.kappa, 'ratio')}
          </div>
        </Panel>
      </div>
      <Panel title="Principal moments and axes" caption="I₁ ≤ I₂ ≤ I₃; axes matched to the body axes, tilt θ = arccos((tr(PᵀV) − 1)/2)">
        <div className="row" style={{ alignItems: 'flex-start', gap: 24 }}>
          <KV
            rows={[
              ['Principal moments', (m.principal_kgm2 as Vec3 | null)?.map((v) => fmt(v, 'kgm2')).join(' · ') ?? '—'],
              ['λ_max (worst axis)', fmt(m.lambda_max_kgm2, 'kgm2')],
              ['Trace T = λ₁ + λ₂ + λ₃', fmt(m.trace_kgm2, 'kgm2')],
              ['Principal-axis tilt', fmt(m.tilt_deg, 'deg')],
              ['Gravity-gradient indicator λ_max − λ_min', m.principal_kgm2 ? fmt((m.principal_kgm2 as Vec3)[2] - (m.principal_kgm2 as Vec3)[0], 'kgm2') : '—'],
            ]}
          />
          {m.principal_axes ? <TensorTable M={m.principal_axes as Mat3} caption="Principal axes (rows, unit vectors in body axes)" names={['axis 1', 'axis 2', 'axis 3']} /> : null}
        </div>
        {contrib?.axes_degenerate ? <Notice tone="info">Axes not unique (moments symmetric within 0.1 %); a Gram–Schmidt basis from the body axes is shown.</Notice> : null}
      </Panel>
      <Panel title="Per-part contribution to tr(I_C)" caption="tr(I_C) = Σ tr(Iᵢ) + 2 Σ mᵢ‖dᵢ‖² · local computation from backend part properties">
        {contrib ? (
          <div className="stack" style={{ gap: 2 }} data-testid="contribution-bars">
            <div className="small muted">dark = own inertia tr(Iᵢ), grey = parallel-axis term 2mᵢ‖dᵢ‖², lever = mᵢ/M (mm of COM per mm of part move)</div>
            {[...contrib.contributions]
              .sort((a, b) => b.self_trace_kgm2 + b.parallel_trace_kgm2 - (a.self_trace_kgm2 + a.parallel_trace_kgm2))
              .map((c) => {
                const tot = c.self_trace_kgm2 + c.parallel_trace_kgm2;
                return (
                  <div key={c.part_id} className="bar-row" title={`${parts[c.part_id]?.name}: own ${fmt(c.self_trace_kgm2, 'kgm2')}, parallel-axis ${fmt(c.parallel_trace_kgm2, 'kgm2')}`}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{parts[c.part_id]?.name ?? c.part_id}</span>
                    <div className="bar-track" aria-hidden="true">
                      <div className="bar-fill" style={{ width: `${(c.self_trace_kgm2 / maxTerm) * 100}%` }} />
                      <div className="bar-fill second" style={{ left: `${(c.self_trace_kgm2 / maxTerm) * 100}%`, width: `${(c.parallel_trace_kgm2 / maxTerm) * 100}%` }} />
                    </div>
                    <span className="num small">
                      {fmt(tot, 'kgm2', { unit: false })} · {fmt(c.lever, 'ratio')}
                    </span>
                  </div>
                );
              })}
          </div>
        ) : (
          <span className="muted">—</span>
        )}
      </Panel>
      <Panel title="What the inertia numbers mean" caption="explainer">
        <p className="small">
          <strong>Agility.</strong> A rest-to-rest slew of angle θ takes t = 2√(θI/T) when torque-limited, or t = θI/h_max + h_max/T when momentum-limited; the worst axis is set by λ_max. No
          wheel data is configured, so no slew times are computed here.
        </p>
        <p className="small">
          <strong>Products of inertia</strong> couple the axes and tilt the principal frame. A 3U is nearly axisymmetric (I_xx ≈ I_yy), so a tiny I_xy can swing the XY principal axes by up to
          45°; the tilt is displayed, not optimised. <strong>Gravity-gradient</strong> torque depends on inertia differences (λ_max − λ_min).
        </p>
      </Panel>
    </div>
  );
}
