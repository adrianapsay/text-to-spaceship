// Exploded view (V2): display-only offsets that pull the parts of a layout apart.
import type { Layout, Vec3 } from '../api/types';

/** How far parts move apart at full explode: each part's offset from the layout centre grows by this factor. */
export const EXPLODE_GAIN = 1.5;

/** Exploded-view offsets (mm): every part moves away from the centre of the layout's part origins, in proportion
 * to its distance, so the arrangement stays recognisable. Display only; nothing is validated in this state. */
export function explodeOffsets(layout: Pick<Layout, 'poses'> | null, k: number): Record<string, Vec3> {
  const out: Record<string, Vec3> = {};
  if (!layout || !(k > 0) || layout.poses.length === 0) return out;
  const n = layout.poses.length;
  const c = [0, 1, 2].map((i) => layout.poses.reduce((s, p) => s + p.t_um[i], 0) / n / 1000);
  for (const p of layout.poses) {
    out[p.part_id] = [0, 1, 2].map((i) => k * EXPLODE_GAIN * (p.t_um[i] / 1000 - c[i])) as Vec3;
  }
  return out;
}
