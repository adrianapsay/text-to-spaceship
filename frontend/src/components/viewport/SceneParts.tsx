import * as THREE from 'three';
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { Outlines } from '@react-three/drei';
import { Label3D } from './labels';
import type { ExtraItem, Mat3, Part, Pose, Vec3 } from '../../api/types';
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
  /** V2 part-size factor of the layout (uniform, about the canonical origin); default 1 */
  scale?: number;
  /** exploded-view offset (mm, world); default none */
  offset?: Vec3;
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
  const ox = p.offset?.[0] ?? 0;
  const oy = p.offset?.[1] ?? 0;
  const oz = p.offset?.[2] ?? 0;
  const target = useMemo(() => {
    const t = poseTRS(p.pose, p.rotations);
    t.position.add(new THREE.Vector3(ox, oy, oz));
    return t;
  }, [p.pose, p.rotations, ox, oy, oz]);
  const scale = p.scale ?? 1;
  const anim = useRef<{ p: THREE.Vector3; q: THREE.Quaternion; start: number } | null>(null);
  const placed = useRef(false);

  useLayoutEffect(() => {
    const g = group.current;
    if (!g) return;
    g.scale.setScalar(scale);
    invalidate();
  }, [scale, invalidate]);

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
      {p.showLabel && geo ? <Label3D position={[p.pose.t_um[0] / 1000 + ox, p.pose.t_um[1] / 1000 + oy, p.pose.t_um[2] / 1000 + oz]} text={p.part.name} priority={p.selected ? 15 : 0} /> : null}
    </group>
  );
}

export function ExtraItemMesh(props: { item: ExtraItem; showLabel: boolean; offset?: Vec3 }) {
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
  const o = props.offset ?? [0, 0, 0];           // exploded view: the item moves with the part it holds
  return (
    <group userData={{ itemId: props.item.id, process: props.item.process }} position={o}>
      <mesh geometry={geo.geometry} material={material} />
      {edges ? <primitive object={edges} /> : null}
      {centre && (st.badge || props.showLabel) ? <Label3D position={[centre.x + o[0], centre.y + o[1], centre.z + o[2]]} text={st.badge ?? st.label} className={st.badge === 'AM' ? 'am' : ''} priority={st.badge ? 20 : 1} /> : null}
    </group>
  );
}
