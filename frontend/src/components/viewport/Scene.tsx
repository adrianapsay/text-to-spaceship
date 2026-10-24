import * as THREE from 'three';
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { useThree } from '@react-three/fiber';
import { CameraControls } from '@react-three/drei';
import type { Layout, Limits, Mat3, Metrics, Part, Stage2Frame, Vec3 } from '../../api/types';
import type { RenderItem } from '../../api/protocol';
import { ramp, STATUS_COLORS, subsystemColor } from '../../lib/colors';
import { matVec } from '../../lib/math3';
import type { ColorMode } from '../../store/store';
import { ComMarkers, CompactnessLine, Enclosure, Violations } from './Markers';
import { ExtraItemMesh, PartObject } from './SceneParts';
import { explodeOffsets } from '../../lib/explode';
import { useCadMouse } from './cadMouse';

export interface SceneView {
  colorMode: ColorMode;
  showEnclosure: boolean;
  showLabels: boolean;
  showCom: boolean;
  showAxes: boolean;
  showBBoxes: boolean;
  hidden: string[];
  isolated: string | null;
  selectedId: string | null;
  hoveredId: string | null;
  /** exploded view, 0 … 1 (display only) */
  explode?: number;
}

const ZERO: Vec3 = [0, 0, 0];

export interface SceneSpec {
  items: RenderItem[];
  parts: Record<string, Part>;
  rotations: Mat3[];
  size: Vec3;
  stage: 1 | 2;
  frame: Stage2Frame | null;
  limits: Limits;
  metrics: Metrics | null;
  target: Vec3;
  prevLayout: Layout | null;
  massOf: (id: string) => number | null;
  view: SceneView;
  interactive: boolean;
  html: boolean;
  tween: boolean;
  onSelect?: (id: string | null) => void;
  onHover?: (id: string | null) => void;
}

export function partColor(spec: Pick<SceneSpec, 'view' | 'prevLayout' | 'massOf' | 'parts'>, part: Part, layout: Layout, maxMass: number, maxDisp: number, locked: boolean): string {
  switch (spec.view.colorMode) {
    case 'status':
      return locked ? STATUS_COLORS.LOCKED : STATUS_COLORS[part.status] ?? STATUS_COLORS.NEEDS_UNITS;
    case 'mass': {
      const m = spec.massOf(part.id);
      return m == null || maxMass <= 0 ? '#A3AAB4' : ramp(m / maxMass);
    }
    case 'displacement': {
      const d = displacement(spec.prevLayout, layout, part.id);
      return d == null || maxDisp <= 0 ? '#A3AAB4' : ramp(d / maxDisp);
    }
    default:
      return subsystemColor(part.subsystem);
  }
}

export function displacement(prev: Layout | null, cur: Layout, id: string): number | null {
  if (!prev) return null;
  const a = prev.poses.find((p) => p.part_id === id);
  const b = cur.poses.find((p) => p.part_id === id);
  if (!a || !b) return null;
  return Math.hypot(b.t_um[0] - a.t_um[0], b.t_um[1] - a.t_um[1], b.t_um[2] - a.t_um[2]) / 1000;
}

export function SceneContent({ spec }: { spec: SceneSpec }) {
  const solid = spec.items.find((i) => i.role === 'best') ?? null;
  const ghosts = spec.items.filter((i) => i.style === 'ghost');
  const visible = (id: string) => (spec.view.isolated ? spec.view.isolated === id : !spec.view.hidden.includes(id));

  const maxMass = useMemo(() => Math.max(0, ...Object.keys(spec.parts).map((id) => spec.massOf(id) ?? 0)), [spec]);
  const maxDisp = useMemo(() => {
    if (!solid) return 0;
    return Math.max(0, ...solid.layout.poses.map((p) => displacement(spec.prevLayout, solid.layout, p.part_id) ?? 0));
  }, [solid, spec.prevLayout]);

  // V2: parts are drawn at the size their layout was found at, and pulled apart in the exploded view
  const scale = solid?.layout.part_scale ?? 1;
  const offsets = useMemo(() => explodeOffsets(solid?.layout ?? null, spec.view.explode ?? 0), [solid, spec.view.explode]);

  const partComs = useMemo(() => {
    if (!solid || !spec.view.showCom) return [];
    const out: Vec3[] = [];
    for (const pose of solid.layout.poses) {
      const part = spec.parts[pose.part_id];
      const R = spec.rotations[pose.orient];
      if (!part?.com_canonical_mm || !R || !visible(pose.part_id)) continue;
      const c = matVec(R, part.com_canonical_mm);
      const o = offsets[pose.part_id] ?? ZERO;
      out.push([c[0] * scale + pose.t_um[0] / 1000 + o[0], c[1] * scale + pose.t_um[1] / 1000 + o[1], c[2] * scale + pose.t_um[2] / 1000 + o[2]]);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [solid, spec.parts, spec.rotations, spec.view.showCom, spec.view.hidden, spec.view.isolated, offsets, scale]);

  const m = spec.metrics;
  return (
    <group>
      <ambientLight intensity={0.55} />
      <directionalLight position={[300, -420, 520]} intensity={1.4} />
      <directionalLight position={[-320, 260, -240]} intensity={0.55} />
      <hemisphereLight args={['#dfe6f0', '#2a2c30', 0.35]} />
      {spec.view.showEnclosure ? <Enclosure size={spec.size} stage={spec.stage} frame={spec.frame} /> : null}
      {solid
        ? solid.layout.poses.map((pose) => {
            const part = spec.parts[pose.part_id];
            if (!part || !visible(pose.part_id)) return null;
            return (
              <PartObject
                key={`s-${pose.part_id}`}
                part={part}
                pose={pose}
                scale={scale}
                offset={offsets[pose.part_id]}
                rotations={spec.rotations}
                color={partColor(spec, part, solid.layout, maxMass, maxDisp, part.locked)}
                style={solid.style}
                selected={spec.view.selectedId === part.id}
                hovered={spec.view.hoveredId === part.id}
                interactive={spec.interactive}
                tween={spec.tween}
                showLabel={spec.html && (spec.view.showLabels || spec.view.selectedId === part.id)}
                showBBox={spec.view.showBBoxes}
                onSelect={(id) => spec.onSelect?.(id)}
                onHover={spec.onHover}
              />
            );
          })
        : null}
      {solid?.layout.extra_items?.map((it) => (
        <ExtraItemMesh key={it.id} item={it} offset={offsets[it.for_part ?? '']} showLabel={spec.html && spec.view.showLabels} />
      ))}
      {ghosts.map((g) =>
        g.layout.poses.map((pose) => {
          const part = spec.parts[pose.part_id];
          if (!part || !visible(pose.part_id)) return null;
          return (
            <PartObject
              key={`g-${g.layout.id}-${pose.part_id}`}
              part={part}
              pose={pose}
              scale={g.layout.part_scale ?? 1}
              rotations={spec.rotations}
              color="#E6E8EB"
              style="ghost"
              selected={false}
              hovered={false}
              interactive={false}
              tween={false}
              showLabel={false}
              showBBox={false}
            />
          );
        }),
      )}
      {spec.view.showCom && m ? (
        <ComMarkers
          com={(m.com_mm as Vec3) ?? null}
          target={spec.target}
          limits={spec.limits}
          stage={spec.stage}
          partComs={partComs}
          principalAxes={(m.principal_axes as Mat3) ?? null}
          principalMoments={(m.principal_kgm2 as Vec3) ?? null}
          tiltDeg={m.tilt_deg ?? null}
          showAxes={spec.view.showAxes}
          showLabels={spec.view.showLabels}
          html={spec.html}
        />
      ) : null}
      {m ? <CompactnessLine lengthUsed={m.length_used_mm ?? null} size={spec.size} html={spec.html} /> : null}
      {solid ? <Violations violations={solid.layout.violations} html={spec.html} /> : null}
    </group>
  );
}

export interface CameraApi {
  fit(animate?: boolean): void;
  view(n: number): void;
  orbit(dAz: number, dPolar: number): void;
  controls(): CameraControls | null;
}

const VIEWS: Record<number, [number, number, number]> = {
  1: [0, -1, 0], // front (−Y)
  2: [0, 1, 0], // back
  3: [-1, 0, 0], // left
  4: [1, 0, 0], // right
  5: [0, -0.0001, 1], // top
  6: [0, -0.0001, -1], // bottom
  0: [0.75, -1, 0.55], // isometric
};

/** Z-up camera with drei CameraControls (CAD-style middle button: cadMouse.ts); exposes fit / standard views / orbit
 * for keyboard handling. */
export const CameraRig = forwardRef<CameraApi, { size: Vec3; fitKey: number; onChange?: () => void }>(function CameraRig(props, ref) {
  const controls = useRef<CameraControls>(null);
  useCadMouse(controls);
  const camera = useThree((s) => s.camera);
  const invalidate = useThree((s) => s.invalidate);
  // fitToSphere keeps the current viewing direction (fitToBox would snap to an axis view)
  const sphere = useMemo(() => new THREE.Sphere(new THREE.Vector3(0, 0, 0), (Math.hypot(props.size[0], props.size[1], props.size[2]) / 2) * 1.02), [props.size]);
  useImperativeHandle(ref, () => {
    const api: CameraApi = {
      fit(animate = true) {
        void controls.current?.fitToSphere(sphere, animate);
        invalidate();
      },
      view(n: number) {
        const d = VIEWS[n];
        if (!d || !controls.current) return;
        const dist = 650;
        const len = Math.hypot(d[0], d[1], d[2]);
        void controls.current.setLookAt((d[0] / len) * dist, (d[1] / len) * dist, (d[2] / len) * dist, 0, 0, 0, false).then(() => api.fit(true));
        invalidate();
      },
      orbit(dAz: number, dPolar: number) {
        void controls.current?.rotate(dAz, dPolar, true);
        invalidate();
      },
      controls: () => controls.current,
    };
    return api;
  });
  useEffect(() => {
    camera.up.set(0, 0, 1);
    const c = controls.current;
    if (!c) return;
    c.updateCameraUp();
    void c.setLookAt(420, -560, 300, 0, 0, 0, false).then(() => c.fitToSphere(sphere, false));
    invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (props.fitKey > 0) void controls.current?.fitToSphere(sphere, true);
  }, [props.fitKey, sphere]);
  return <CameraControls ref={controls} makeDefault onChange={() => props.onChange?.()} />;
});

/** Keyboard map for a focused viewport: F fit, 1–6 views, 0 iso, arrows orbit, H/I/Shift+H hide/isolate/show all, E enclosure. */
export function viewportKeyHandler(
  cam: () => CameraApi | null,
  actions: { hide?: () => void; isolate?: () => void; showAll?: () => void; toggleEnclosure?: () => void },
) {
  return (e: React.KeyboardEvent) => {
    const c = cam();
    const k = e.key;
    if (k === 'f' || k === 'F') c?.fit();
    else if (/^[0-6]$/.test(k)) c?.view(Number(k));
    else if (k === 'ArrowLeft') c?.orbit(-0.15, 0);
    else if (k === 'ArrowRight') c?.orbit(0.15, 0);
    else if (k === 'ArrowUp') c?.orbit(0, -0.12);
    else if (k === 'ArrowDown') c?.orbit(0, 0.12);
    else if ((k === 'h' || k === 'H') && e.shiftKey) actions.showAll?.();
    else if (k === 'h' || k === 'H') actions.hide?.();
    else if (k === 'i' || k === 'I') actions.isolate?.();
    else if (k === 'e' || k === 'E') actions.toggleEnclosure?.();
    else return;
    e.preventDefault();
    e.stopPropagation();
  };
}
