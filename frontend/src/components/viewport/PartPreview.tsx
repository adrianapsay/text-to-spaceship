import * as THREE from 'three';
import { Canvas } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import type { Part, Vec3 } from '../../api/types';
import { subsystemColor } from '../../lib/colors';
import { useApp } from '../../store/store';
import { CameraRig, viewportKeyHandler, type CameraApi } from './Scene';
import { PartObject } from './SceneParts';

/** Single-part inspector view in the part's local (canonical) frame, with its axes and COM. */
export function PartPreview({ part }: { part: Part }) {
  const rotations = useApp((s) => s.dataset.rotations);
  const cam = useRef<CameraApi>(null);
  const pose = useMemo(() => ({ part_id: part.id, orient: 0, t_um: [0, 0, 0] as Vec3 }), [part.id]);
  const size = useMemo(() => part.extents_mm.map((v) => Math.max(v, 1) * 1.4) as Vec3, [part.extents_mm]);
  const axes = useMemo(() => new THREE.AxesHelper(Math.max(...part.extents_mm) * 0.7), [part.extents_mm]);
  const com = useMemo(() => {
    if (!part.com_canonical_mm) return null;
    const m = new THREE.Mesh(new THREE.SphereGeometry(Math.max(...part.extents_mm) * 0.025, 16, 12), new THREE.MeshBasicMaterial({ color: '#FFFFFF', depthTest: false }));
    m.position.set(...part.com_canonical_mm);
    m.renderOrder = 999;
    return m;
  }, [part.com_canonical_mm, part.extents_mm]);
  return (
    <div className="viewport-wrap" style={{ height: 300, flex: 'none' }} tabIndex={0} role="region" aria-label={`Part ${part.name} in its own frame`} onKeyDown={viewportKeyHandler(() => cam.current, {})}>
      <Canvas frameloop="demand" dpr={[1, 2]} camera={{ position: [200, -260, 160], up: [0, 0, 1], fov: 35, near: 0.1, far: 20000 }}>
        <color attach="background" args={['#26282C']} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[300, -420, 520]} intensity={1.4} />
        <directionalLight position={[-320, 260, -240]} intensity={0.5} />
        <CameraRig ref={cam} size={size} fitKey={0} />
        {rotations.length ? (
          <PartObject
            part={part}
            pose={pose}
            rotations={rotations}
            color={subsystemColor(part.subsystem)}
            style="solid"
            selected={false}
            hovered={false}
            interactive={false}
            tween={false}
            showLabel={false}
            showBBox
          />
        ) : null}
        <primitive object={axes} />
        {com ? <primitive object={com} /> : null}
      </Canvas>
      <div className="vp-overlay tl">
        <span className="vp-chip">part frame (canonical) · axes x red, y green, z blue · white dot = COM</span>
      </div>
    </div>
  );
}
