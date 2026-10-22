import * as THREE from 'three';
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { Html, Outlines } from '@react-three/drei';
import type { ExtraItem, Mat3, Part, Pose } from '../../api/types';
import type { RenderStyle } from '../../api/protocol';
import { VIEWPORT, extraItemStyle } from '../../lib/colors';
import { poseTRS, useItemGeometry, usePartGeometry } from './geometry';
import { createSolidMaterial, extraItemMaterial } from './materials';

export const TWEEN_MS = 300;

function mixColor(a: string, b: string, t: number): string {
  const ca = new THREE.Color(a);
  const cb = new THREE.Color(b);
  return `#${ca.lerp(cb, t).getHexString()}`;
}

function dashedBox(ext: [number, number, number], color: string, dash = 3, gap = 2): THREE.LineSegments {
  const g = new THREE.EdgesGeometry(new THREE.BoxGeometry(ext[0], ext[1], ext[2]));
  const ls = new THREE.LineSegments(g, new THREE.LineDashedMaterial({ color, dashSize: dash, gapSize: gap, transparent: true, opacity: 0.8 }));
  ls.computeLineDistances();
  return ls;
}

export interface PartObjectProps {
  part: Part;
  pose: Pose;
  rotations: Mat3[];
  color: string;
  style: RenderStyle;
  selected: boolean;
  hovered: boolean;
  interactive: boolean;
  tween: boolean;
  showLabel: boolean;
  showBBox: boolean;
  onSelect?: (id: string) => void;
  onHover?: (id: string | null) => void;
}

export function PartObject(p: PartObjectProps) {
  const geo = usePartGeometry(p.part);
  const group = useRef<THREE.Group>(null);
  const invalidate = useThree((s) => s.invalidate);
  const target = useMemo(() => poseTRS(p.pose, p.rotations), [p.pose, p.rotations]);
  const anim = useRef<{ p: THREE.Vector3; q: THREE.Quaternion; start: number } | null>(null);
  const placed = useRef(false);

  useLayoutEffect(() => {
    const g = group.current;
    if (!g) return;
    if (!placed.current || !p.tween) {
      g.position.copy(target.position);
      g.quaternion.copy(target.quaternion);
      placed.current = true;
      anim.current = null;
    } else {
      anim.current = { p: g.position.clone(), q: g.quaternion.clone(), start: performance.now() };
    }
    invalidate();
  }, [target, p.tween, invalidate]);

  useFrame(() => {
    const a = anim.current;
    const g = group.current;
    if (!a || !g) return;
    const t = Math.min(1, (performance.now() - a.start) / TWEEN_MS);
    const e = t * t * (3 - 2 * t);
    g.position.lerpVectors(a.p, target.position, e);
    g.quaternion.slerpQuaternions(a.q, target.quaternion, e);
    if (t < 1) invalidate();
    else anim.current = null;
  });

  const shownColor = p.style === 'stale' ? mixColor(p.color, VIEWPORT.stale, 0.6) : p.color;
  const material = useMemo(() => createSolidMaterial(shownColor, { opacity: p.style === 'stale' ? 0.9 : 1 }), [shownColor, p.style]);
  useEffect(() => () => material.dispose(), [material]);

  const edgeObj = useMemo(() => {
    if (!geo) return null;
    if (p.style === 'ghost') {
      const ls = new THREE.LineSegments(geo.edges, new THREE.LineDashedMaterial({ color: VIEWPORT.ghost, dashSize: 1.2, gapSize: 1.6, transparent: true, opacity: 0.9 }));
      ls.computeLineDistances();
      ls.userData.ghost = true;
      return ls;
    }
    return new THREE.LineSegments(geo.edges, new THREE.LineBasicMaterial({ color: VIEWPORT.edges, transparent: true, opacity: 0.85 }));
  }, [geo, p.style]);
  useEffect(() => () => (edgeObj?.material as THREE.Material | undefined)?.dispose(), [edgeObj]);

  const bbox = useMemo(() => (p.showBBox ? dashedBox(p.part.extents_mm, VIEWPORT.label) : null), [p.showBBox, p.part.extents_mm]);

  const handlers = p.interactive && p.style !== 'ghost'
    ? {
        onClick: (e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          p.onSelect?.(p.part.id);
        },
        onPointerOver: (e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation();
          p.onHover?.(p.part.id);
        },
        onPointerOut: () => p.onHover?.(null),
      }
    : {};

  return (
    <group ref={group} userData={{ partId: p.part.id, style: p.style }}>
      {geo && p.style !== 'ghost' ? (
        <mesh geometry={geo.geometry} material={material} userData={{ partId: p.part.id }} {...handlers}>
          {p.selected ? <Outlines thickness={2.5} color={VIEWPORT.select} /> : p.hovered ? <Outlines thickness={1.5} color={VIEWPORT.hover} /> : null}
        </mesh>
      ) : null}
      {edgeObj ? <primitive object={edgeObj} /> : null}
      {bbox ? <primitive object={bbox} /> : null}
      {p.showLabel && geo ? (
        <Html center zIndexRange={[20, 10]} style={{ pointerEvents: 'none' }}>
          <div className="vp-label" role="note">
            {p.part.name}
          </div>
        </Html>
      ) : null}
    </group>
  );
}

export function ExtraItemMesh(props: { item: ExtraItem; showLabel: boolean }) {
  const geo = useItemGeometry(props.item.mesh_url);
  const st = extraItemStyle(props.item.process);
  const material = useMemo(() => extraItemMaterial(String(props.item.process)), [props.item.process]);
  useEffect(() => () => material.dispose(), [material]);
  const edges = useMemo(() => (geo ? new THREE.LineSegments(geo.edges, new THREE.LineBasicMaterial({ color: VIEWPORT.edges })) : null), [geo]);
  const centre = useMemo(() => {
    if (!geo?.geometry.boundingBox) return null;
    return geo.geometry.boundingBox.getCenter(new THREE.Vector3());
  }, [geo]);
  if (!geo) return null;
  return (
    <group userData={{ itemId: props.item.id, process: props.item.process }}>
      <mesh geometry={geo.geometry} material={material} />
      {edges ? <primitive object={edges} /> : null}
      {centre && (st.badge || props.showLabel) ? (
        <Html position={centre} center zIndexRange={[25, 15]} style={{ pointerEvents: 'none' }}>
          <div className={`vp-label ${st.badge === 'AM' ? 'am' : ''}`}>{st.badge ?? st.label}</div>
        </Html>
      ) : null}
    </group>
  );
}
