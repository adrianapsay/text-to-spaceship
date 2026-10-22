import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { View } from '@react-three/drei';
import { useLayoutEffect, useMemo, useRef } from 'react';
import type { Layout, Vec3 } from '../../api/types';
import { displayKind, styleFor } from '../../api/protocol';
import { useApp, displayMass } from '../../store/store';
import { SceneContent, type SceneSpec } from './Scene';

function FixedCamera() {
  const set = useThree((s) => s.set);
  const cam = useMemo(() => {
    const c = new THREE.PerspectiveCamera(30, 1, 1, 20000);
    c.up.set(0, 0, 1);
    c.position.set(520, -700, 380);
    c.lookAt(0, 0, 0);
    return c;
  }, []);
  useLayoutEffect(() => set({ camera: cam }), [cam, set]);
  return <primitive object={cam} />;
}

/** Many small static 3D thumbnails rendered by ONE canvas (scissored drei Views). */
export function ThumbGrid(props: { entries: { key: string; title: string; layout: Layout | null }[] }) {
  const container = useRef<HTMLDivElement>(null!);
  const parts = useApp((s) => s.dataset.parts);
  const rotations = useApp((s) => s.dataset.rotations);
  const project = useApp((s) => s.dataset.project);
  const newest = useApp((s) => s.conn.newest);
  const physical = useApp((s) => s.physical);
  const dataset = useApp((s) => s.dataset);
  const size = (project?.enclosure.size_mm as Vec3 | undefined) ?? [100, 100, 340.5];
  const spec = (layout: Layout): SceneSpec => {
    const kind = displayKind(layout, newest, 'archive');
    return {
      items: [{ layout, role: 'best', kind, style: styleFor(kind) }],
      parts,
      rotations,
      size,
      stage: layout.stage,
      frame: project?.stage2_frame ?? null,
      limits: project?.limits ?? {},
      metrics: layout.metrics,
      target: [0, 0, 0],
      prevLayout: null,
      massOf: (id) => displayMass({ physical, dataset } as never, id),
      view: { colorMode: 'subsystem', showEnclosure: true, showLabels: false, showCom: false, showAxes: false, showBBoxes: false, hidden: [], isolated: null, selectedId: null, hoveredId: null },
      interactive: false,
      html: false,
      tween: false,
    };
  };
  return (
    <div ref={container} style={{ position: 'relative', display: 'flex', flexWrap: 'wrap', gap: 6 }} data-testid="thumb-grid">
      {props.entries.map((e, i) => (
        <figure key={e.key} style={{ margin: 0, width: 140 }}>
          <div style={{ position: 'relative', width: 140, height: 180, background: 'var(--viewport)' }}>
            {e.layout ? (
              <View style={{ position: 'absolute', inset: 0 }} index={i + 1} frames={2}>
                <FixedCamera />
                <SceneContent spec={spec(e.layout)} />
              </View>
            ) : (
              <span className="vp-overlay tl">no layout</span>
            )}
          </div>
          <figcaption className="small">{e.title}</figcaption>
        </figure>
      ))}
      <Canvas eventSource={container} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }} frameloop="demand" dpr={[1, 1.5]}>
        <View.Port />
      </Canvas>
    </div>
  );
}
