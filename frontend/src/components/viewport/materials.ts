import * as THREE from 'three';
import { extraItemStyle } from '../../lib/colors';

/**
 * Diagonal-hatch material for metal 3D-printed brackets: screen-space stripes darken every other band, so the
 * pattern (not only the colour) identifies AM parts (Addendum 1.5).
 */
export function createHatchMaterial(color: string, opts: { opacity?: number } = {}): THREE.MeshStandardMaterial {
  const m = new THREE.MeshStandardMaterial({
    color,
    metalness: 0.2,
    roughness: 0.6,
    flatShading: true,
    transparent: (opts.opacity ?? 1) < 1,
    opacity: opts.opacity ?? 1,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  });
  m.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <dithering_fragment>',
      `#include <dithering_fragment>
       float hatchBand = mod(gl_FragCoord.x + gl_FragCoord.y, 10.0);
       if (hatchBand < 4.0) gl_FragColor.rgb *= 0.42;`,
    );
  };
  m.customProgramCacheKey = () => 'hatch-diagonal-v1';
  m.userData.hatch = true;
  return m;
}

export function createSolidMaterial(color: string, opts: { opacity?: number; metalness?: number; roughness?: number } = {}): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color,
    metalness: opts.metalness ?? 0.05,
    roughness: opts.roughness ?? 0.75,
    flatShading: true,
    transparent: (opts.opacity ?? 1) < 1,
    opacity: opts.opacity ?? 1,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  });
}

/** Material for an extra item (bracket) by process; metal AM gets the hatch. */
export function extraItemMaterial(process: string): THREE.MeshStandardMaterial {
  const st = extraItemStyle(process);
  const m = st.hatch ? createHatchMaterial(st.color) : createSolidMaterial(st.color, { metalness: st.metalness, roughness: st.roughness });
  m.userData.process = process;
  return m;
}

function canvasTexture(draw: (ctx: CanvasRenderingContext2D, s: number) => void, size = 64): THREE.Texture | null {
  if (typeof document === 'undefined') return null;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  if (!ctx) return null;
  draw(ctx, size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

let quartered: THREE.Texture | null | undefined;
/** Assembly COM marker: quartered disc (black/white), the standard centre-of-mass symbol. */
export function quarteredDiscTexture(): THREE.Texture | null {
  if (quartered === undefined)
    quartered = canvasTexture((ctx, s) => {
      const r = s / 2 - 3;
      ctx.translate(s / 2, s / 2);
      ctx.fillStyle = '#FFFFFF';
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#111317';
      for (const a0 of [0, Math.PI]) {
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, r, a0, a0 + Math.PI / 2);
        ctx.closePath();
        ctx.fill();
      }
      ctx.strokeStyle = '#111317';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.stroke();
    });
  return quartered;
}

let ringed: THREE.Texture | null | undefined;
/** Part COM marker: ringed dot. */
export function ringedDotTexture(): THREE.Texture | null {
  if (ringed === undefined)
    ringed = canvasTexture((ctx, s) => {
      ctx.translate(s / 2, s / 2);
      ctx.fillStyle = '#111317';
      ctx.beginPath();
      ctx.arc(0, 0, s / 2 - 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#FFFFFF';
      ctx.beginPath();
      ctx.arc(0, 0, s / 2 - 12, 0, Math.PI * 2);
      ctx.fill();
    });
  return ringed;
}
