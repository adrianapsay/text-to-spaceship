// V2: a designed bracket's FEA results as colour maps (Components tab). The mesh is the designed solid itself
// (GET /api/items/{id}/mesh), coloured per vertex by one result field (GET /api/items/{id}/fea/{field}): unlit, so
// shading never reads as a value, with its feature edges for the shape. Beside it: the legend, every check as a
// utilisation bar (1 = zero margin) and the margins table (the table view of the same numbers).
import * as THREE from 'three';
import { Canvas, useThree, type ThreeEvent } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { BracketDesign, FeaField, FeaView, Vec3 } from '../api/types';
import { session } from '../api/session';
import { useAsync } from '../hooks';
import { CRITICAL, VIEWPORT_BG, checkBars, fieldValueText, rampGradient, scaleFor, vertexColors } from '../lib/feaColors';
import { CameraRig, viewportKeyHandler, type CameraApi } from './viewport/Scene';
import { useItemGeometry } from './viewport/geometry';
import { MarginsTable, governingText } from './BracketDesign';
import { Badge, Button, KV, Notice, Panel } from './ui';

const KIND_GROUP: Record<string, string> = { utilisation: 'Utilisation', stress: 'Stress (von Mises)', displacement: 'Displacement' };

function groups(fields: FeaField[]): [string, FeaField[]][] {
  const m = new Map<string, FeaField[]>();
  for (const f of fields) {
    const g = KIND_GROUP[f.kind] ?? f.kind;
    m.set(g, [...(m.get(g) ?? []), f]);
  }
  return [...m.entries()];
}

/** Legend of a colour map: the ramp from 0 to the field's largest value (the number the margins use), and for the
 * utilisation the critical colour named "≥ 1.00 fails". */
export function FeaLegend({ field, darkSurface = true }: { field: FeaField; darkSurface?: boolean }) {
  const s = scaleFor(field);
  const mid = (s.min + s.max) / 2;
  return (
    <div className="fea-legend" data-testid="fea-legend">
      <div className="fea-ramp" style={{ background: rampGradient(darkSurface) }} aria-hidden="true" />
      <div className="fea-ticks small">
        <span>{fieldValueText(s.min, field)}</span>
        <span>{fieldValueText(mid, field)}</span>
        <span>
          {fieldValueText(s.max, field)}
          {field.kind === 'utilisation' ? ' (zero margin)' : ' (largest, as in the margins)'}
        </span>
      </div>
      {s.threshold != null ? (
        <div className="small row" style={{ gap: 6, marginTop: 4 }}>
          <span className="swatch" style={{ background: CRITICAL }} aria-hidden="true" />
          <span>⚠ ≥ {s.threshold.toFixed(2)}: fails (negative margin)</span>
        </div>
      ) : null}
    </div>
  );
}

/** Every check as a bar of its utilisation (factor × stress / allowable, or bolt load / capacity; 1 = zero margin),
 * largest first; a line marks the allowable. Labels: the largest and any failing one; the rest on hover / focus. */
export function UtilisationChart({ design, limit = 8 }: { design: BracketDesign; limit?: number }) {
  const bars = useMemo(() => checkBars(design.checks, design.bolt_checks), [design.checks, design.bolt_checks]);
  const [all, setAll] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  if (!bars.length) return <span className="muted small">No per-check results (designed before the launch environments).</span>;
  const shown = all ? bars : bars.slice(0, limit);
  const xmax = Math.max(1.1, ...shown.map((b) => b.u)) * 1.05;
  const pct = (x: number) => `${(100 * Math.min(x, xmax)) / xmax}%`;
  return (
    <div className="ubars viz-root" data-testid="utilisation-chart">
      {shown.map((b, i) => {
        const fails = b.gates && b.u >= 1;
        const label = i === 0 || fails;
        return (
          <div
            key={b.key}
            className={`ubar-row ${b.gates ? '' : 'estimate'}`}
            tabIndex={0}
            onMouseEnter={() => setHover(b.key)}
            onMouseLeave={() => setHover((h) => (h === b.key ? null : h))}
            onFocus={() => setHover(b.key)}
            onBlur={() => setHover((h) => (h === b.key ? null : h))}
            aria-label={`${b.label}: utilisation ${b.u.toFixed(2)}, ${b.detail}${b.gates ? '' : ' (estimate, not a pass criterion)'}`}
          >
            <span className="ubar-label small">
              {b.label}
              {b.gates ? '' : ' (estimate)'}
            </span>
            <span className="ubar-track">
              <span className="ubar" style={{ width: pct(b.u) }} />
              <span className="ubar-allow" style={{ left: pct(1) }} />
              {hover === b.key ? (
                <span className="ubar-tip small" role="tooltip">
                  {b.detail}
                  {b.gates ? '' : ' — an ESTIMATE, reported only'}
                </span>
              ) : null}
            </span>
            <span className="ubar-value small num">{label || hover === b.key ? `${fails ? '✗ ' : ''}${b.u.toFixed(2)}${fails ? ' fails' : ''}` : ''}</span>
          </div>
        );
      })}
      <div className="ubar-row axis" aria-hidden="true">
        <span className="ubar-label" />
        <span className="ubar-track">
          <span className="ubar-tick" style={{ left: '0%' }}>
            0
          </span>
          <span className="ubar-tick" style={{ left: pct(0.5) }}>
            0.5
          </span>
          <span className="ubar-tick" style={{ left: pct(1) }}>
            1.0 allowable
          </span>
        </span>
        <span className="ubar-value" />
      </div>
      {bars.length > limit ? (
        <Button size="small" onClick={() => setAll((v) => !v)} style={{ marginTop: 4 }}>
          {all ? `Show the ${limit} largest` : `Show all ${bars.length} checks`}
        </Button>
      ) : null}
    </div>
  );
}

function ColoredMesh(props: { meshUrl: string; values: Float32Array | null; field: FeaField; onHover: (v: { value: number; x: number; y: number } | null) => void }) {
  const base = useItemGeometry(props.meshUrl);
  const invalidate = useThree((s) => s.invalidate);
  const geo = useMemo(() => {
    if (!base) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', base.geometry.getAttribute('position'));
    const idx = base.geometry.getIndex();
    if (idx) g.setIndex(idx);
    g.computeBoundingBox();
    g.computeBoundingSphere();
    return g;
  }, [base]);
  useEffect(() => () => geo?.dispose(), [geo]);
  const n = geo ? geo.getAttribute('position').count : 0;
  const ok = !!props.values && props.values.length === n;
  useEffect(() => {
    if (!geo) return;
    const colors = ok ? vertexColors(props.values as Float32Array, scaleFor(props.field), true) : new Float32Array(n * 3).fill(0.5);
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    invalidate();
  }, [geo, props.values, props.field, ok, n, invalidate]);
  const centre = useMemo(() => {
    const c = new THREE.Vector3();
    geo?.boundingBox?.getCenter(c);
    return c;
  }, [geo]);
  if (!geo || !base) return null;
  const move = (e: ThreeEvent<PointerEvent>) => {
    if (!ok || !e.face) return;
    const p = e.object.worldToLocal(e.point.clone());
    const pos = geo.getAttribute('position');
    let best = e.face.a;
    let bd = Infinity;
    for (const i of [e.face.a, e.face.b, e.face.c]) {
      const d = p.distanceToSquared(new THREE.Vector3(pos.getX(i), pos.getY(i), pos.getZ(i)));
      if (d < bd) {
        bd = d;
        best = i;
      }
    }
    props.onHover({ value: (props.values as Float32Array)[best], x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY });
  };
  return (
    <group position={[-centre.x, -centre.y, -centre.z]}>
      <mesh geometry={geo} onPointerMove={move} onPointerOut={() => props.onHover(null)}>
        <meshBasicMaterial vertexColors side={THREE.DoubleSide} />
      </mesh>
      <lineSegments geometry={base.edges}>
        <lineBasicMaterial color="#898781" />
      </lineSegments>
    </group>
  );
}

const CASE_FIELD: Record<string, string> = { static: 'vm_static', 'random limit': 'vm_random_limit', 'random qualification': 'vm_random_qual' };

/** The colour map to open on: the stress of the body check with the smallest margin (its own 0 … largest range shows
 * where the bracket works hardest even when it is far from its limit); utilisation when no such check exists. */
export function governingField(d: Pick<BracketDesign, 'checks'>): string {
  const body = (d.checks ?? []).filter((r) => r.gates && r.case in CASE_FIELD);
  if (!body.length) return 'util_body';
  const g = body.reduce((a, b) => (Math.min(b.ms_yield, b.ms_ult) < Math.min(a.ms_yield, a.ms_ult) ? b : a));
  return `${CASE_FIELD[g.case]}_${g.axis}`;
}

function ms(v: number | null | undefined) {
  if (v == null) return <span className="muted">—</span>;
  return <Badge tone={v >= 0 ? 'ok' : 'err'}>{(v >= 0 ? '+' : '') + v.toFixed(2)}</Badge>;
}

/** A designed bracket in the Components tab: its colour maps, its numbers, every check as a bar and the margins. */
export function BracketFeaPanel(props: { itemId: string; meshUrl: string; design: BracketDesign; title: string; target?: string }) {
  const { design: d } = props;
  const view = useAsync(() => session().api.itemFea(props.itemId), [props.itemId, d.mass_kg, d.fea_file]);
  const settings = d.settings;
  return (
    <div className="grid-2" data-testid="bracket-fea">
      <Panel title={`FEA colour map — ${props.title}`} caption={`${d.environment_name ?? d.environment ?? 'launch loads'} · ${d.material_name ?? d.material ?? ''}`}>
        {view.data?.available ? (
          <FeaViewer view={view.data} meshUrl={props.meshUrl} initialField={governingField(d)} />
        ) : (
          <Notice tone="info">{view.loading ? 'Loading the colour maps…' : view.data?.why ?? view.error ?? 'No colour maps for this bracket.'}</Notice>
        )}
      </Panel>
      <Panel title="Checks" caption="margins of safety from two FEA solvers (CalculiX and NGSolve); 1.00 utilisation = zero margin">
        <KV
          rows={[
            ['Result', d.passed ? <Badge tone="ok">passes every check</Badge> : <Badge tone="err">fails: {d.reason || 'see the checks'}</Badge>],
            ['Governing check', d.governing ? `${governingText(d.governing)} — MS ${(d.governing.ms >= 0 ? '+' : '') + d.governing.ms.toFixed(2)}` : '—'],
            ['MS yield / ultimate / bolts', <span className="row" style={{ gap: 4 }}>{ms(d.ms_yield)}{ms(d.ms_ult)}{ms(d.ms_bolt)}</span>],
            ['First natural frequency', d.f1_hz != null ? `${Math.round(d.f1_hz)} Hz${d.modes?.[0] ? ` (${d.modes[0].motion})` : ''}` : '—'],
            ['Solid / with fasteners', `${d.solid_mass_kg != null ? `${(1000 * d.solid_mass_kg).toFixed(1)} g` : '—'} / ${(1000 * d.mass_kg).toFixed(1)} g`],
            ['Designed with', settings ? `${settings.material}; material used ${settings.vol_frac === 'auto' ? `automatic${d.vol_frac != null ? ` (${Math.round(100 * d.vol_frac)} %)` : ''}` : `${Math.round(100 * settings.vol_frac)} %`}; member ${settings.min_member_mm === 'auto' ? 'automatic' : `${settings.min_member_mm} mm`}` : d.generator],
            ['Fixed to', props.target ?? '—'],
          ]}
        />
        <h4 className="small" style={{ margin: '10px 0 4px' }}>
          Utilisation per check
        </h4>
        <UtilisationChart design={d} />
        {d.margins ? (
          <>
            <h4 className="small" style={{ margin: '10px 0 4px' }}>
              Margins per load case (table view)
            </h4>
            <MarginsTable margins={d.margins} />
          </>
        ) : null}
      </Panel>
    </div>
  );
}

/** The colour-mapped bracket with its field selector, hover readout and legend. */
export function FeaViewer({ view, meshUrl, initialField }: { view: FeaView; meshUrl: string; initialField?: string }) {
  const fields = useMemo(() => view.fields ?? [], [view.fields]);
  const [fieldId, setFieldId] = useState(fields.some((f) => f.id === initialField) ? (initialField as string) : (fields[0]?.id ?? ''));
  useEffect(() => {
    if (!fields.some((f) => f.id === fieldId)) setFieldId(fields[0]?.id ?? '');
  }, [fields, fieldId]);
  const field = fields.find((f) => f.id === fieldId) ?? fields[0];
  const values = useAsync(field ? () => session().api.itemFeaField(view.item_id, field.id) : null, [view.item_id, field?.id]);
  const [hover, setHover] = useState<{ value: number; x: number; y: number } | null>(null);
  const cam = useRef<CameraApi>(null);
  const base = useItemGeometry(meshUrl);
  const size = useMemo((): Vec3 => {
    const b = base?.geometry.boundingBox;
    if (!b) return [40, 40, 40];
    const s = new THREE.Vector3();
    b.getSize(s);
    return [Math.max(s.x, 1) * 1.15, Math.max(s.y, 1) * 1.15, Math.max(s.z, 1) * 1.15];
  }, [base]);
  if (!field) return <Notice tone="info">{view.why ?? 'No colour maps for this bracket.'}</Notice>;
  return (
    <div data-testid="fea-viewer">
      <div className="row small" style={{ marginBottom: 6 }}>
        <label htmlFor="fea-field" style={{ fontWeight: 600 }}>
          Show
        </label>
        <select id="fea-field" value={field.id} onChange={(ev) => setFieldId(ev.target.value)} data-testid="fea-field">
          {groups(fields).map(([g, fs]) => (
            <optgroup key={g} label={g}>
              {fs.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>
      <div
        className="viewport-wrap fea-canvas"
        style={{ height: 320, flex: 'none', position: 'relative' }}
        tabIndex={0}
        role="region"
        aria-label={`${field.label}, colour map on the bracket`}
        onKeyDown={viewportKeyHandler(() => cam.current, {})}
      >
        <Canvas frameloop="demand" dpr={[1, 2]} camera={{ position: [200, -260, 160], up: [0, 0, 1], fov: 35, near: 0.1, far: 20000 }}>
          <color attach="background" args={[VIEWPORT_BG]} />
          <CameraRig ref={cam} size={size} fitKey={base ? 1 : 0} />
          <ColoredMesh meshUrl={meshUrl} values={values.data} field={field} onHover={setHover} />
        </Canvas>
        {hover ? (
          <div className="vp-chip fea-hover" style={{ left: hover.x + 12, top: hover.y + 12 }} role="status">
            {fieldValueText(hover.value, field)}
          </div>
        ) : null}
        <div className="vp-overlay tl">
          <span className="vp-chip">{values.loading ? 'loading the field…' : values.error ? `field not loaded: ${values.error}` : field.label}</span>
        </div>
      </div>
      <FeaLegend field={field} />
      <div className="small muted" style={{ marginTop: 4 }}>
        Largest on the surface {fieldValueText(field.max, field)}; over every voxel {fieldValueText(field.max_all, field)}. {view.note}
      </div>
    </div>
  );
}
