import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { CameraControls, View } from '@react-three/drei';
import { useCallback, useLayoutEffect, useMemo, useRef, type ReactNode } from 'react';
import type { Layout, Metrics, Vec3 } from '../../api/types';
import { badgeText, type RenderItem } from '../../api/protocol';
import { sub, norm } from '../../lib/math3';
import { fmt, fmtVec } from '../../lib/fmt';
import { useApp, displayMass } from '../../store/store';
import { MovementArrows } from './Markers';
import { SceneContent, type SceneSpec } from './Scene';

export interface DualSide {
  label: string;
  items: RenderItem[];
  metrics: Metrics | null;
  stage: 1 | 2;
  empty?: ReactNode;
}

function ViewCamera(props: { camera: THREE.PerspectiveCamera }) {
  const set = useThree((s) => s.set);
  useLayoutEffect(() => {
    set({ camera: props.camera });
  }, [props.camera, set]);
  return <primitive object={props.camera} />;
}

function makeCamera(): THREE.PerspectiveCamera {
  const c = new THREE.PerspectiveCamera(35, 1, 1, 20000);
  c.up.set(0, 0, 1);
  c.position.set(420, -560, 300);
  c.lookAt(0, 0, 0);
  return c;
}

function partCentres(layout: Layout | null): Record<string, Vec3> {
  const out: Record<string, Vec3> = {};
  if (!layout) return out;
  for (const p of layout.poses) out[p.part_id] = [p.t_um[0] / 1000, p.t_um[1] / 1000, p.t_um[2] / 1000];
  return out;
}

/** One canvas, two scissored drei <View>s sharing geometry, with linked cameras and a movement overlay. */
export function DualViewport(props: { left: DualSide; right: DualSide; testId?: string; movement?: boolean }) {
  const container = useRef<HTMLDivElement>(null!);
  const parts = useApp((s) => s.dataset.parts);
  const rotations = useApp((s) => s.dataset.rotations);
  const project = useApp((s) => s.dataset.project);
  const settings = useApp((s) => s.goals.settings);
  const view = useApp((s) => s.view);
  const physical = useApp((s) => s.physical);
  const dataset = useApp((s) => s.dataset);
  const setFlag = useApp((s) => s.setViewFlag);
  const select = useApp((s) => s.select);
  const size = (project?.enclosure.size_mm as Vec3 | undefined) ?? [100, 100, 340.5];
  const camA = useMemo(makeCamera, []);
  const camB = useMemo(makeCamera, []);
  const ctlA = useRef<CameraControls>(null);
  const ctlB = useRef<CameraControls>(null);
  const syncing = useRef(false);
  const link = view.linkCameras;
  const massOf = useCallback((id: string) => displayMass({ physical, dataset } as never, id), [physical, dataset]);

  const sync = (from: CameraControls | null, to: CameraControls | null) => {
    if (!link || !from || !to || syncing.current) return;
    syncing.current = true;
    const p = from.getPosition(new THREE.Vector3());
    const t = from.getTarget(new THREE.Vector3());
    void to.setLookAt(p.x, p.y, p.z, t.x, t.y, t.z, false);
    syncing.current = false;
  };

  const specFor = (side: DualSide): SceneSpec => ({
    items: side.items,
    parts,
    rotations,
    size,
    stage: side.stage,
    frame: project?.stage2_frame ?? null,
    limits: project?.limits ?? {},
    metrics: side.metrics,
    target: settings?.target_com_mm ?? [0, 0, 0],
    prevLayout: null,
    massOf,
    view: {
      colorMode: view.colorMode === 'displacement' ? 'subsystem' : view.colorMode,
      showEnclosure: view.showEnclosure,
      showLabels: false,
      showCom: view.showCom,
      showAxes: view.showAxes,
      showBBoxes: false,
      hidden: view.hidden,
      isolated: view.isolated,
      selectedId: view.selectedPartId,
      hoveredId: null,
    },
    interactive: true,
    html: false,
    tween: false,
    onSelect: select,
  });

  const lb = props.left.items.find((i) => i.role === 'best')?.layout ?? null;
  const rb = props.right.items.find((i) => i.role === 'best')?.layout ?? null;
  const centresL = partCentres(lb);
  const centresR = partCentres(rb);
  const pairs = useMemo(
    () =>
      Object.keys(centresR)
        .filter((id) => centresL[id])
        .map((id) => ({ from: centresL[id], to: centresR[id] })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lb, rb],
  );
  const comL = (props.left.metrics?.com_mm as Vec3 | undefined) ?? null;
  const comR = (props.right.metrics?.com_mm as Vec3 | undefined) ?? null;
  const dCom = comL && comR ? sub(comR, comL) : null;
  const showMove = (props.movement ?? true) && view.showMovement;

  const badge = (side: DualSide) => {
    const b = side.items.find((i) => i.role === 'best');
    return (
      <div className="vp-overlay tl">
        <span className="vp-chip">{side.stage === 2 ? 'STAGE 2 ENGINEERING-CONSTRAINED (ASSUMED frame)' : 'STAGE 1 IDEALIZED'}</span>
        <div>
          <span className="vp-chip">{side.label}</span> {b ? <span className={`vp-chip ${b.style === 'stale' ? 'warn' : ''}`}>{badgeText(b.kind)}</span> : null}
        </div>
      </div>
    );
  };

  return (
    <div className="stack" style={{ flex: 1, minHeight: 0, gap: 0 }} data-testid={props.testId ?? 'dual-viewport'}>
      <div className="vp-toolbar" role="toolbar" aria-label="Comparison view options">
        <button type="button" className="btn small" aria-pressed={link} onClick={() => setFlag('linkCameras', !link)}>
          Link cameras
        </button>
        <button type="button" className="btn small" aria-pressed={view.showMovement} onClick={() => setFlag('showMovement', !view.showMovement)}>
          Movement overlay
        </button>
        <span className="small muted" style={{ marginLeft: 8 }} data-testid="delta-com">
          ΔCOM {dCom ? `${fmt(norm(dCom), 'mm')} · ${fmtVec(dCom)}` : '—'}
        </span>
      </div>
      <div ref={container} className="dual-views" style={{ position: 'relative' }}>
        <div className="view-slot">
          {props.left.items.length ? <View style={{ position: 'absolute', inset: 0 }} index={1}>
            <ViewCamera camera={camA} />
            <CameraControls ref={ctlA} camera={camA} onChange={() => sync(ctlA.current, ctlB.current)} />
            <SceneContent spec={specFor(props.left)} />
          </View> : <div className="vp-overlay tl" style={{ top: 60 }}>{props.left.empty}</div>}
          {badge(props.left)}
        </div>
        <div className="view-slot">
          {props.right.items.length ? <View style={{ position: 'absolute', inset: 0 }} index={2}>
            <ViewCamera camera={camB} />
            <CameraControls ref={ctlB} camera={camB} onChange={() => sync(ctlB.current, ctlA.current)} />
            <SceneContent spec={specFor(props.right)} />
            {showMove ? <MovementArrows pairs={pairs} comFrom={comL} comTo={comR} /> : null}
          </View> : <div className="vp-overlay tl" style={{ top: 60, pointerEvents: 'auto' }}>{props.right.empty}</div>}
          {badge(props.right)}
          {showMove && dCom ? (
            <div className="vp-overlay br">
              <span className="vp-chip">
                ΔCOM {fmt(norm(dCom), 'mm')} (Δx, Δy, Δz) = {fmtVec(dCom)}
              </span>
            </div>
          ) : null}
        </div>
        <Canvas
          eventSource={container}
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
          frameloop="demand"
          dpr={[1, 2]}
          gl={{ antialias: true }}
          onCreated={(st) => {
            (st.raycaster as unknown as { firstHitOnly: boolean }).firstHitOnly = true;
            st.gl.setClearColor('#26282C');
          }}
        >
          <View.Port />
        </Canvas>
      </div>
    </div>
  );
}
