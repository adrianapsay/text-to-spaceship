// Colour tokens for the 3D viewport and charts (protocol §I.1). Identity never relies on colour alone:
// labels, list entries, badges and patterns carry the meaning too.

export const VIEWPORT = {
  background: '#26282C',
  enclosure: '#8C929B',
  label: '#E6E8EB',
  edges: '#141518',
  hover: '#5D96F0',
  select: '#FFFFFF',
  accent: '#5D96F0',
  collision: '#D55E00',
  clearance: '#E69F00',
  stale: '#7A818C',
  ghost: '#E6E8EB',
} as const;

/** Okabe-Ito by subsystem; blue #0072B2 dropped (too little contrast on the viewport). */
export const SUBSYSTEM_COLORS: Record<string, string> = {
  power: '#E69F00',
  electronics: '#56B4E9',
  adcs: '#009E73',
  tanks: '#F0E442',
  payload: '#CC79A7',
  structure: '#8C929B',
  unknown: '#D4D7DB',
};

export const SUBSYSTEM_LABELS: Record<string, string> = {
  power: 'Power',
  electronics: 'Electronics',
  adcs: 'ADCS',
  tanks: 'Tanks',
  payload: 'Payload / sensors',
  structure: 'Structure',
  unknown: 'Unknown',
};

export function subsystemColor(s: string | null | undefined): string {
  return SUBSYSTEM_COLORS[s ?? 'unknown'] ?? SUBSYSTEM_COLORS.unknown;
}

export const STATUS_COLORS: Record<string, string> = {
  VALID: '#5CC08A',
  REPAIRED: '#E3B341',
  WITHHELD: '#F2877A',
  NEEDS_UNITS: '#A3AAB4',
  LOCKED: '#5D96F0',
};

/** Sequential ramp readable on the dark viewport (low → high). */
export function ramp(t: number): string {
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  const a = [0x7a, 0x8b, 0xa8];
  const m = [0x3f, 0xb8, 0xaf];
  const b = [0xfd, 0xe9, 0x45];
  const lerp = (p: number[], q: number[], u: number) => p.map((v, i) => Math.round(v + (q[i] - v) * u));
  const c = x < 0.5 ? lerp(a, m, x * 2) : lerp(m, b, (x - 0.5) * 2);
  return `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

/** Categorical colours for algorithms in charts and selector strips (stable by sorted id). */
export const ALGO_PALETTE = ['#56B4E9', '#E69F00', '#009E73', '#CC79A7', '#F0E442', '#8C929B', '#D4D7DB', '#B48CFF'];
export function algoColor(id: string, all: string[]): string {
  const sorted = [...new Set(all)].sort();
  const i = sorted.indexOf(id);
  return ALGO_PALETTE[(i < 0 ? 0 : i) % ALGO_PALETTE.length];
}

// ------------------------------------------------------------------------------------- extra items (brackets)
export interface ExtraItemStyle {
  color: string;
  /** diagonal hatch / stripe material (the pattern carries the meaning, safe for colour-blind users) */
  hatch: boolean;
  /** 3D / list badge */
  badge: 'AM' | null;
  /** hardware-list section */
  section: 'METAL 3D-PRINTED' | 'OTHER HARDWARE';
  label: string;
  metalness: number;
  roughness: number;
}

const METAL_AM: ExtraItemStyle = {
  color: '#B48CFF',
  hatch: true,
  badge: 'AM',
  section: 'METAL 3D-PRINTED',
  label: 'Metal 3D-printed bracket (AM)',
  metalness: 0.2,
  roughness: 0.6,
};

export const EXTRA_ITEM_STYLES: Record<string, ExtraItemStyle> = {
  metal_am: METAL_AM,
  sheet: { color: '#B8BEC6', hatch: false, badge: null, section: 'OTHER HARDWARE', label: 'Sheet-metal bracket', metalness: 0.4, roughness: 0.5 },
  machined: { color: '#9AA3AE', hatch: false, badge: null, section: 'OTHER HARDWARE', label: 'Machined bracket', metalness: 0.45, roughness: 0.4 },
  catalogue: { color: '#C9CDD3', hatch: false, badge: null, section: 'OTHER HARDWARE', label: 'Catalogue part', metalness: 0.3, roughness: 0.5 },
  direct: { color: '#6F7782', hatch: false, badge: null, section: 'OTHER HARDWARE', label: 'Direct mount (fasteners)', metalness: 0.3, roughness: 0.6 },
  card_guide: { color: '#A7B5C4', hatch: false, badge: null, section: 'OTHER HARDWARE', label: 'Card guide', metalness: 0.3, roughness: 0.5 },
  standoff: { color: '#B5B0A2', hatch: false, badge: null, section: 'OTHER HARDWARE', label: 'Standoff', metalness: 0.3, roughness: 0.5 },
};

export function extraItemStyle(process: string | null | undefined): ExtraItemStyle {
  return EXTRA_ITEM_STYLES[process ?? ''] ?? { color: '#A3AAB4', hatch: false, badge: null, section: 'OTHER HARDWARE', label: process ?? 'Hardware', metalness: 0.3, roughness: 0.5 };
}

export function isMetalAm(process: string | null | undefined): boolean {
  return extraItemStyle(process).badge === 'AM';
}

// ------------------------------------------------------------------------------------- contrast utilities
export function relativeLuminance(hex: string): number {
  const h = hex.replace('#', '');
  const v = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = v.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
