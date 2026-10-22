// DOM labels for the 3D viewport without per-label React roots: labels are registered from inside the Canvas,
// rendered as plain DOM in an overlay layer outside it, and positioned each rendered frame by projecting their
// world positions with the active camera. Screen readers read them as ordinary text.

import * as THREE from 'three';
import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useFrame, useThree } from '@react-three/fiber';

export interface LabelSpec {
  position: [number, number, number];
  text: ReactNode;
  className?: string;
  offset?: [number, number];
  /** declutter priority: higher wins when labels overlap */
  priority?: number;
}

export class LabelHub {
  readonly labels = new Map<string, LabelSpec>();
  readonly elements = new Map<string, HTMLElement>();
  private subs = new Set<() => void>();
  version = 0;
  /** set by the projector: asks the demand frame loop for one more frame */
  requestFrame: (() => void) | null = null;
  set(id: string, spec: LabelSpec) {
    this.labels.set(id, spec);
    this.bump();
  }
  delete(id: string) {
    if (this.labels.delete(id)) this.bump();
  }
  subscribe(cb: () => void) {
    this.subs.add(cb);
    return () => {
      this.subs.delete(cb);
    };
  }
  private bump() {
    this.version++;
    queueMicrotask(() => this.subs.forEach((s) => s()));
  }
}

export const LabelContext = createContext<LabelHub | null>(null);

/** Register a label at a world position (inside the Canvas). Renders nothing in the 3D scene. */
export function Label3D(props: LabelSpec) {
  const hub = useContext(LabelContext);
  const id = useId();
  const invalidate = useThree((s) => s.invalidate);
  const key = `${props.position.join(',')}|${props.className ?? ''}|${typeof props.text === 'string' ? props.text : ''}`;
  useEffect(() => {
    if (!hub) return;
    hub.set(id, props);
    invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hub, id, key, props.text]);
  useEffect(() => () => hub?.delete(id), [hub, id]);
  return null;
}

/** Inside the Canvas: projects every registered label each rendered frame. */
export function LabelProjector() {
  const hub = useContext(LabelContext);
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const v = useRef(new THREE.Vector3());
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    if (!hub) return;
    hub.requestFrame = () => invalidate();
    return () => {
      hub.requestFrame = null;
    };
  }, [hub, invalidate]);
  useFrame(() => {
    if (!hub) return;
    // declutter: greedy placement in priority order (higher first); a label overlapping a placed one is hidden
    const placed: [number, number, number, number][] = [];
    const entries = [...hub.labels.entries()].sort((a, b) => (b[1].priority ?? 0) - (a[1].priority ?? 0));
    for (const [id, spec] of entries) {
      const el = hub.elements.get(id);
      if (!el) continue;
      v.current.set(...spec.position).project(camera);
      const behind = v.current.z > 1 || v.current.z < -1;
      const x = ((v.current.x + 1) / 2) * size.width + (spec.offset?.[0] ?? 0);
      const y = ((1 - v.current.y) / 2) * size.height + (spec.offset?.[1] ?? 0);
      const w = el.offsetWidth || 60;
      const h = el.offsetHeight || 16;
      const r: [number, number, number, number] = [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
      const overlaps = placed.some((p) => r[0] < p[2] && r[2] > p[0] && r[1] < p[3] && r[3] > p[1]);
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -50%)`;
      const show = !behind && !overlaps;
      el.style.visibility = show ? 'visible' : 'hidden';
      if (show) placed.push(r);
    }
  });
  return null;
}

/** Outside the Canvas: the DOM layer that holds the label elements. */
export function LabelLayer({ hub }: { hub: LabelHub }) {
  const [, setV] = useState(0);
  useEffect(() => hub.subscribe(() => setV(hub.version)), [hub]);
  const entries = [...hub.labels.entries()];
  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 1 }} aria-label="3D labels">
      {entries.map(([id, spec]) => (
        <LabelEl key={id} id={id} hub={hub} spec={spec} />
      ))}
    </div>
  );
}

function LabelEl({ id, hub, spec }: { id: string; hub: LabelHub; spec: LabelSpec }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (ref.current) hub.elements.set(id, ref.current);
    hub.requestFrame?.();
    return () => {
      hub.elements.delete(id);
    };
  }, [hub, id]);
  return (
    <div ref={ref} className={`vp-label ${spec.className ?? ''}`} style={{ position: 'absolute', left: 0, top: 0, visibility: 'hidden', willChange: 'transform' }}>
      {spec.text}
    </div>
  );
}
