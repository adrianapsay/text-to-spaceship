// V3 CubeSat Builder — 3D Spacecraft Preview: the CubeSat envelope with its parts in an illustrative arrangement
// (arrange.ts), external hardware on the faces and marked "not packed". Parts with imported CAD (the maker's model or a
// reconstruction) are drawn with it, turned to lie as their box does; the others as boxes of their published size. It
// shows sizes and where things go, not the optimiser's packing; parts without a published size are drawn as small
// stand-ins and listed.
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { Canvas } from '@react-three/fiber';
import type { Vec3 } from '../api/types';
import { CameraRig, viewportKeyHandler, type CameraApi } from '../components/viewport/Scene';
import type { Analysis } from './analysisTypes';
import { arrange, axisTurn, drawPlan, MESH_MAX_FACES, type PlacedBox } from './arrange';
import { Badge, Notice, Panel } from '../components/ui';

/** Fetches a part's STL (mm, centred) — the API client's builderCadStl. */
export type StlLoad = (cid: string, v?: string) => Promise<ArrayBuffer>;

// one parse per imported model: keyed by the part and its import time (a re-import is a new key)
const parsed = new Map<string, Promise<THREE.BufferGeometry>>();

function modelGeometry(load: StlLoad, cid: string, v?: string): Promise<THREE.BufferGeometry> {
  const key = `${cid}@${v ?? ''}`;
  let p = parsed.get(key);
  if (!p) {
    p = load(cid, v).then((buf) => {
      const g = new STLLoader().parse(buf);
      g.computeVertexNormals();
      return g;
    });
    p.catch(() => parsed.delete(key));
    parsed.set(key, p);
  }
  return p;
}

const SLOT_COLOR: Record<string, string> = {
  payload: '#E8A33D', adcs: '#5DA5DA', wheels: '#5DA5DA', magnetorquer: '#5DA5DA', star_tracker: '#5DA5DA',
  sun_sensor: '#5DA5DA', gnss: '#B276B2', obc: '#60BD68', eps: '#F15854', battery: '#F17CB0', solar: '#4D4D9A',
  radio_ttc: '#DECF3F', antenna_ttc: '#DECF3F', radio_data: '#FAA43A', antenna_data: '#FAA43A', propulsion: '#B2912F',
};

function Box({ b }: { b: PlacedBox }) {
  const color = b.overflow ? '#FF3B30' : SLOT_COLOR[b.slot] ?? '#999999';
  return (
    <mesh position={b.center}>
      <boxGeometry args={b.size} />
      <meshStandardMaterial color={color} transparent opacity={b.external ? 0.55 : b.unsized ? 0.35 : 0.9} wireframe={b.unsized} />
    </mesh>
  );
}

/** A part drawn with its imported model, turned so its sides lie as its box's do; the box until the model arrives. */
function Model({ b, cid, extents, v, load }: { b: PlacedBox; cid: string; extents: number[]; v?: string; load: StlLoad }) {
  const [geo, setGeo] = useState<THREE.BufferGeometry | null>(null);
  useEffect(() => {
    let live = true;
    modelGeometry(load, cid, v).then(
      (g) => live && setGeo(g),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [load, cid, v]);
  const turn = useMemo(() => {
    const m = axisTurn(extents, b.size);
    const r = new THREE.Matrix4().set(m[0][0], m[0][1], m[0][2], 0, m[1][0], m[1][1], m[1][2], 0, m[2][0], m[2][1], m[2][2], 0, 0, 0, 0, 1);
    return new THREE.Quaternion().setFromRotationMatrix(r);
  }, [extents, b.size]);
  if (!geo) return <Box b={b} />;
  return (
    // dispose={null}: the geometry is shared by every copy of the part and kept for the next render
    <mesh geometry={geo} position={b.center} quaternion={turn} dispose={null}>
      <meshStandardMaterial color={SLOT_COLOR[b.slot] ?? '#999999'} transparent={b.external} opacity={b.external ? 0.8 : 1} />
    </mesh>
  );
}

function Envelope({ outer }: { outer: [number, number, number] }) {
  const edges = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(...outer)), [outer]);
  return (
    <lineSegments geometry={edges}>
      <lineBasicMaterial color="#C8CCD2" />
    </lineSegments>
  );
}

export function PreviewSection(props: { a: Analysis; stale: boolean; loadStl?: StlLoad }) {
  const { a, loadStl } = props;
  const { outer, boxes } = useMemo(() => arrange(a), [a]);
  const plan = useMemo(() => drawPlan(boxes, a.geometry), [boxes, a.geometry]);
  const withModel = new Set(plan.filter((p) => p.model && loadStl).map((p) => p.box.name));
  const heavy = [...new Set(plan.filter((p) => p.heavy).map((p) => p.box.name))];
  const cam = useRef<CameraApi>(null);
  const span = useMemo(() => {
    const ext = boxes.reduce((m, b) => Math.max(m, ...b.center.map((c, i) => Math.abs(c) + b.size[i] / 2)), 0);
    const r = Math.max(ext, ...outer.map((v) => v / 2)) * 2;
    return [r, r, r] as Vec3;
  }, [boxes, outer]);
  const unsized = boxes.filter((b) => b.unsized);
  const over = boxes.filter((b) => b.overflow);
  const seen = new Set<string>();
  const legend = boxes.filter((b) => {
    const k = `${b.slot}:${b.name}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return (
    <div className="grid-2" data-testid="preview" aria-busy={props.stale}>
      <Panel
        title={`3D preview — ${a.size_label}`}
        caption="an illustrative arrangement: sizes and where things go, not the optimiser's packing; parts with imported CAD drawn with it, the others as boxes"
      >
        <div
          className="viewport-wrap"
          style={{ height: 460, flex: 'none', opacity: props.stale ? 0.55 : 1 }}
          tabIndex={0}
          role="region"
          aria-label="3D preview of the design"
          onKeyDown={viewportKeyHandler(() => cam.current, {})}
        >
          <Canvas frameloop="demand" dpr={[1, 2]} camera={{ position: [420, -520, 300], up: [0, 0, 1], fov: 35, near: 0.1, far: 50000 }}>
            <color attach="background" args={['#26282C']} />
            <ambientLight intensity={0.7} />
            <directionalLight position={[300, -420, 520]} intensity={1.3} />
            <directionalLight position={[-320, 260, -240]} intensity={0.5} />
            <CameraRig ref={cam} size={span} fitKey={a.size_u} />
            <Envelope outer={outer} />
            {plan.map(({ box: b, cid, model }) =>
              model && loadStl ? (
                <Model key={b.id} b={b} cid={cid} extents={model.extents_mm} v={model.imported} load={loadStl} />
              ) : (
                <Box key={b.id} b={b} />
              ),
            )}
          </Canvas>
          <div className="vp-overlay tl">
            <span className="vp-chip">−Z is the nadir end (camera) · F to fit · 1–6 views</span>
          </div>
        </div>
      </Panel>
      <Panel title="In the preview">
        {props.stale ? <Notice tone="info">Recomputing — showing design version {a.design_version}.</Notice> : null}
        {over.length ? <Notice tone="err">Does not fit as arranged: {over.map((b) => b.name).join(', ')}.</Notice> : null}
        {unsized.length ? <Notice tone="warn">Size not published (drawn as 20 mm stand-ins): {[...new Set(unsized.map((b) => b.name))].join(', ')}.</Notice> : null}
        {heavy.length ? (
          <Notice tone="info">
            Imported CAD too detailed to draw here (over {MESH_MAX_FACES.toLocaleString('en-US')} triangles), shown as boxes: {heavy.join(', ')}.
          </Notice>
        ) : null}
        <ul className="small" style={{ listStyle: 'none', padding: 0, margin: 0 }} data-testid="preview-legend">
          {legend.map((b) => (
            <li key={`${b.slot}:${b.name}`} className="row" style={{ gap: 6 }}>
              <span aria-hidden style={{ width: 12, height: 12, background: SLOT_COLOR[b.slot] ?? '#999', display: 'inline-block' }} />
              {b.name}
              {withModel.has(b.name) ? <Badge tone="ok">imported CAD</Badge> : null}
              {b.external ? <Badge tone="neutral">not packed</Badge> : null}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
