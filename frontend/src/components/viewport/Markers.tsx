import * as THREE from 'three';
import { useEffect, useMemo } from 'react';
import { useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import type { Limits, Mat3, Stage2Frame, Vec3, Violation } from '../../api/types';
import { VIEWPORT } from '../../lib/colors';
import { fmt } from '../../lib/fmt';
import { quarteredDiscTexture, ringedDotTexture } from './materials';

function lineObject(points: Vec3[], color: string, opts: { dashed?: boolean; dash?: number; gap?: number; opacity?: number; onTop?: boolean } = {}): THREE.LineSegments {
  const g = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(...p)));
  const mat = opts.dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: opts.dash ?? 4, gapSize: opts.gap ?? 3, transparent: true, opacity: opts.opacity ?? 1 })
    : new THREE.LineBasicMaterial({ color, transparent: true, opacity: opts.opacity ?? 1 });
  if (opts.onTop) {
    mat.depthTest = false;
  }
  const ls = new THREE.LineSegments(g, mat);
  if (opts.dashed) ls.computeLineDistances();
  if (opts.onTop) ls.renderOrder = 900;
  return ls;
}

function boxEdges(min: Vec3, max: Vec3): Vec3[] {
  const [x0, y0, z0] = min;
  const [x1, y1, z1] = max;
  const c: Vec3[] = [
    [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
    [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
  ];
  const e = [
    [0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7],
  ];
  return e.flatMap(([a, b]) => [c[a], c[b]]);
}

function useDisposable<T extends THREE.Object3D>(obj: T | null): T | null {
  useEffect(
    () => () => {
      if (!obj) return;
      obj.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose?.();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
        else mat?.dispose?.();
      });
    },
    [obj],
  );
  return obj;
}

export function Enclosure(props: { size: Vec3; stage: 1 | 2; frame: Stage2Frame | null; showFaces?: boolean }) {
  const half: Vec3 = [props.size[0] / 2, props.size[1] / 2, props.size[2] / 2];
  const outer = useDisposable(useMemo(() => lineObject(boxEdges([-half[0], -half[1], -half[2]], half), VIEWPORT.enclosure), [half[0], half[1], half[2]]));
  const frameObj = useDisposable(
    useMemo(() => {
      if (props.stage !== 2 || !props.frame) return null;
      const g = new THREE.Group();
      for (const b of props.frame.boxes ?? []) {
        const size = [b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]];
        const mesh = new THREE.Mesh(
          new THREE.BoxGeometry(size[0], size[1], size[2]),
          new THREE.MeshStandardMaterial({ color: '#8C929B', transparent: true, opacity: 0.35, flatShading: true, depthWrite: false }),
        );
        mesh.position.set((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
        g.add(mesh);
        g.add(lineObject(boxEdges(b.min, b.max), VIEWPORT.enclosure));
      }
      if (props.frame.walls) g.add(lineObject(boxEdges(props.frame.walls.inner_min, props.frame.walls.inner_max), VIEWPORT.enclosure, { dashed: true, opacity: 0.8 }));
      return g;
    }, [props.stage, props.frame]),
  );
  return (
    <group>
      {outer ? <primitive object={outer} /> : null}
      {frameObj ? <primitive object={frameObj} /> : null}
    </group>
  );
}

function PointsMarker(props: { positions: Vec3[]; sizePx: number; texture: THREE.Texture | null; onTop?: boolean; color?: string }) {
  const dpr = useThree((s) => s.viewport.dpr);
  const obj = useDisposable(
    useMemo(() => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(props.positions.flat(), 3));
      const m = new THREE.PointsMaterial({
        size: props.sizePx * dpr,
        sizeAttenuation: false,
        map: props.texture ?? undefined,
        color: props.color ?? '#FFFFFF',
        transparent: true,
        alphaTest: 0.4,
        depthTest: !props.onTop,
      });
      const pts = new THREE.Points(g, m);
      if (props.onTop) pts.renderOrder = 1000;
      return pts;
    }, [props.positions, props.sizePx, props.texture, props.onTop, props.color, dpr]),
  );
  return obj ? <primitive object={obj} /> : null;
}

export interface ComMarkerProps {
  com: Vec3 | null;
  target: Vec3;
  limits: Limits;
  stage: 1 | 2;
  partComs: Vec3[];
  principalAxes: Mat3 | null;
  principalMoments: Vec3 | null;
  tiltDeg: number | null;
  showAxes: boolean;
  showLabels: boolean;
  html: boolean;
}

export function ComMarkers(p: ComMarkerProps) {
  const box = (p.limits.com_box_mm as Vec3 | undefined) ?? [20, 20, 70];
  const cds = useDisposable(
    useMemo(
      () => lineObject(boxEdges([-box[0], -box[1], -box[2]], box), VIEWPORT.accent, { dashed: p.stage === 1, dash: 5, gap: 4, opacity: p.stage === 1 ? 0.8 : 1 }),
      [box[0], box[1], box[2], p.stage],
    ),
  );
  const cross = useDisposable(
    useMemo(() => {
      const [x, y, z] = p.target;
      const s = 8;
      return lineObject(
        [
          [x - s, y, z], [x + s, y, z], [x, y - s, z], [x, y + s, z], [x, y, z - s], [x, y, z + s],
        ],
        VIEWPORT.accent,
        { onTop: true },
      );
    }, [p.target]),
  );
  const toCom = useDisposable(useMemo(() => (p.com ? lineObject([p.target, p.com], VIEWPORT.label, { onTop: true, opacity: 0.9 }) : null), [p.com, p.target]));
  const axes = useDisposable(
    useMemo(() => {
      if (!p.showAxes || !p.com || !p.principalAxes) return null;
      const g = new THREE.Group();
      const colors = ['#F2877A', '#5CC08A', '#5D96F0'];
      const L = 60;
      p.principalAxes.forEach((ax, k) => {
        const a: Vec3 = [p.com![0] - ax[0] * L, p.com![1] - ax[1] * L, p.com![2] - ax[2] * L];
        const b: Vec3 = [p.com![0] + ax[0] * L, p.com![1] + ax[1] * L, p.com![2] + ax[2] * L];
        g.add(lineObject([a, b], colors[k], { onTop: true }));
        const body: Vec3 = [0, 0, 0];
        body[k] = L;
        g.add(
          lineObject([[p.com![0] - body[0], p.com![1] - body[1], p.com![2] - body[2]], [p.com![0] + body[0], p.com![1] + body[1], p.com![2] + body[2]]], colors[k], {
            dashed: true,
            dash: 3,
            gap: 3,
            opacity: 0.6,
            onTop: true,
          }),
        );
      });
      return g;
    }, [p.showAxes, p.com, p.principalAxes]),
  );
  const dist = p.com ? Math.hypot(p.com[0] - p.target[0], p.com[1] - p.target[1], p.com[2] - p.target[2]) : null;
  const ringTex = useMemo(() => ringedDotTexture(), []);
  const discTex = useMemo(() => quarteredDiscTexture(), []);
  return (
    <group>
      {cds ? <primitive object={cds} /> : null}
      {cross ? <primitive object={cross} /> : null}
      {p.partComs.length ? <PointsMarker positions={p.partComs} sizePx={6} texture={ringTex} /> : null}
      {toCom ? <primitive object={toCom} /> : null}
      {p.com ? <PointsMarker positions={[p.com]} sizePx={16} texture={discTex} onTop /> : null}
      {axes ? <primitive object={axes} /> : null}
      {p.html && p.com && dist !== null ? (
        <Html position={[(p.com[0] + p.target[0]) / 2 + 4, (p.com[1] + p.target[1]) / 2, (p.com[2] + p.target[2]) / 2]} zIndexRange={[30, 20]} style={{ pointerEvents: 'none' }}>
          <div className="vp-label">target → COM {fmt(dist, 'mm')}</div>
        </Html>
      ) : null}
      {p.html ? (
        <Html position={[box[0], -box[1], box[2]]} zIndexRange={[30, 20]} style={{ pointerEvents: 'none' }}>
          <div className="vp-label">{p.stage === 2 ? 'CDS COM box — HARD' : 'CDS COM box (shown, not enforced in Stage 1)'}</div>
        </Html>
      ) : null}
      {p.html && p.showAxes && p.com && p.principalMoments ? (
        <Html position={[p.com[0] + 62, p.com[1], p.com[2]]} zIndexRange={[30, 20]} style={{ pointerEvents: 'none' }}>
          <div className="vp-label">
            I₁ ≤ I₂ ≤ I₃ · tilt {fmt(p.tiltDeg, 'deg')}
          </div>
        </Html>
      ) : null}
    </group>
  );
}

export function CompactnessLine(props: { lengthUsed: number | null; size: Vec3; html: boolean }) {
  const z0 = -props.size[2] / 2;
  const x = props.size[0] / 2 + 8;
  const y = -props.size[1] / 2;
  const obj = useDisposable(
    useMemo(() => {
      if (props.lengthUsed == null) return null;
      const z1 = z0 + props.lengthUsed;
      return lineObject(
        [
          [x, y, z0], [x, y, z1],
          [x - 4, y, z0], [x + 4, y, z0],
          [x - 4, y, z1], [x + 4, y, z1],
          [x, y, z0 + props.size[2]], [x + 4, y, z0 + props.size[2]],
        ],
        VIEWPORT.label,
      );
    }, [props.lengthUsed, z0, x, y, props.size]),
  );
  if (!obj) return null;
  return (
    <group>
      <primitive object={obj} />
      {props.html ? (
        <Html position={[x + 6, y, z0 + (props.lengthUsed ?? 0) / 2]} zIndexRange={[30, 20]} style={{ pointerEvents: 'none' }}>
          <div className="vp-label">
            used {fmt(props.lengthUsed, 'mm', { unit: false })} / {fmt(props.size[2], 'mm')}
          </div>
        </Html>
      ) : null}
    </group>
  );
}

/** Clearance / collision indicators: drawn ONLY from backend verdicts (layout.violations), never computed here. */
export function Violations(props: { violations: Violation[] | undefined; html: boolean }) {
  const obj = useDisposable(
    useMemo(() => {
      const v = props.violations?.filter((x) => x.points) ?? [];
      if (!v.length) return null;
      const g = new THREE.Group();
      for (const x of v) g.add(lineObject([x.points![0], x.points![1]], x.kind === 'overlap' ? VIEWPORT.collision : VIEWPORT.clearance, { onTop: true }));
      return g;
    }, [props.violations]),
  );
  if (!obj) return null;
  return (
    <group>
      <primitive object={obj} />
      {props.html
        ? props.violations
            ?.filter((x) => x.points)
            .map((x, i) => (
              <Html key={i} position={x.points![0]} zIndexRange={[30, 20]} style={{ pointerEvents: 'none' }}>
                <div className="vp-label" style={{ borderColor: x.kind === 'overlap' ? VIEWPORT.collision : VIEWPORT.clearance }}>
                  {x.kind === 'overlap' ? 'OVERLAP' : `${fmt(x.distance_mm, 'clearance', { unit: false })} / ${fmt(x.required_mm ?? null, 'clearance')}`}
                </div>
              </Html>
            ))
        : null}
    </group>
  );
}

export function MovementArrows(props: { pairs: { from: Vec3; to: Vec3 }[]; comFrom: Vec3 | null; comTo: Vec3 | null }) {
  const obj = useDisposable(
    useMemo(() => {
      const g = new THREE.Group();
      for (const p of props.pairs) {
        const a = new THREE.Vector3(...p.from);
        const b = new THREE.Vector3(...p.to);
        const d = b.clone().sub(a);
        const len = d.length();
        if (len < 0.5) continue;
        g.add(new THREE.ArrowHelper(d.normalize(), a, len, 0xe6e8eb, Math.min(8, len * 0.3), Math.min(4, len * 0.15)));
      }
      if (props.comFrom && props.comTo) {
        const a = new THREE.Vector3(...props.comFrom);
        const b = new THREE.Vector3(...props.comTo);
        const d = b.clone().sub(a);
        const len = d.length();
        if (len > 0.05) {
          const arrow = new THREE.ArrowHelper(d.normalize(), a, len, 0x5d96f0, Math.min(10, len * 0.3), Math.min(5, len * 0.15));
          arrow.renderOrder = 950;
          arrow.traverse((o) => {
            const m = (o as THREE.Mesh).material as THREE.Material | undefined;
            if (m) m.depthTest = false;
          });
          g.add(arrow);
        }
      }
      return g;
    }, [props.pairs, props.comFrom, props.comTo]),
  );
  return obj ? <primitive object={obj} /> : null;
}
