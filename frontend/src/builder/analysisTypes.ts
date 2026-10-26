// V3 CubeSat Builder: the shapes of the analysis (/api/builder/designs/{id}/analysis) and the catalog
// (/api/builder/catalog); backend t2s/builder/engine.py, recommend.py, compat.py, analysis/calc.py.

export interface CalcInput {
  value: unknown;
  unit: string | null;
  source: string;
}

/** One traceable calculation: value, equation, inputs with sources, assumptions, references and fidelity. */
export interface Calc {
  id: string;
  label: string;
  value: unknown;
  unit: string | null;
  equation: string;
  inputs: Record<string, CalcInput>;
  assumptions: string[];
  refs: string[];
  fidelity: 'conceptual' | 'preliminary';
  explain: string;
  /** set when the value could not be computed: what is needed */
  missing: string | null;
  ok?: boolean | null;
  meets?: boolean;
  feasible?: boolean;
  need?: number;
  [extra: string]: unknown;
}

export interface Price {
  value: number | null;
  currency: string | null;
  kind: string;
  note: string;
}

export interface PartSummary {
  id: string;
  category: string;
  category_name?: string;
  manufacturer?: string;
  product?: string;
  description?: string | null;
  fits?: string | null;
  mass_kg: number | null;
  dims_mm: number[] | null;
  power_w: { typical: number | null; peak?: number | null; standby?: number | null };
  price: Price;
  cad: string;
  datasheet_url?: string | null;
  url?: string | null;
}

export interface PickItem extends PartSummary {
  name: string;
  qty: number;
  placeholder?: boolean;
}

export interface Alternative {
  id: string;
  name: string;
  score: number | null;
  reason: string;
}

export type PickStatus = 'recommended' | 'user' | 'none' | 'missing' | 'placeholder';

export interface Pick {
  slot: string;
  label: string;
  items: PickItem[];
  status: PickStatus;
  why: string;
  need: string;
  alternatives: Alternative[];
  flags: string[];
  place: 'internal' | 'external' | 'frame';
  score?: number;
  /** when the user chose: what the architect recommended */
  recommended?: { items: { id: string; name: string; qty: number }[]; status: string; why: string };
}

export type CheckStatus = 'compatible' | 'assumptions' | 'incompatible' | 'unknown';

export interface Check {
  rule: string;
  status: CheckStatus;
  status_text: string;
  title: string;
  detail: string;
  items: string[];
  fix: string;
  source: string;
}

export interface TradeRow {
  size_u: number;
  label: string;
  failures: string[];
  feasible: boolean;
  alt_km: number;
  mass_kg: number;
  mass_limit_kg: number;
  margin_pct: number | null;
  data_pct: number | null;
  fill_pct: number;
  cost: Record<string, number>;
  quotes: number;
  payload: string[];
  gsd_m: number | null;
  checks: Record<CheckStatus, number>;
}

export interface Slider {
  label: string;
  low: string;
  high: string;
  default: number;
}

export interface RefInfo {
  key: string;
  title: string;
  publisher: string;
  url: string;
  accessed: string;
}

export interface Orbit {
  choice: string;
  alt_km: number;
  inc_deg: number;
  ltdn_h: number | null;
  sso: boolean;
  why: string;
  flags: string[];
}

export interface Analysis {
  engine: string;
  computed_at: string;
  design_id: string;
  /** the design version this analysis describes (compare with the design's own version: never show stale as current) */
  design_version: number;
  inputs_hash: string;
  cached: boolean;
  fidelity: string;
  mission_years: number;
  prefs: Record<string, number>;
  size_u: number;
  size_label: string;
  size_why: string;
  size_user: boolean;
  orbit: Orbit;
  picks: Record<string, Pick>;
  slots: { id: string; label: string; place: string }[];
  calcs: Record<string, Calc>;
  groups: { id: string; label: string; calcs: string[] }[];
  checks: Check[];
  check_summary: { counts: Record<CheckStatus, number>; overall: CheckStatus };
  trade: TradeRow[];
  failures: string[];
  missing_hardware: string[];
  flags: string[];
  sliders: Record<string, Slider>;
  refs: Record<string, RefInfo>;
  disclaimer: string;
  /** questions not answered yet: the analysis used their documented defaults (ASSUMED) */
  open_questions: { qid: string; prompt: string; advanced: boolean; default: string; why: string }[];
  /** the geometry of the picked parts that have one (CAD or simplified shapes), by catalog id */
  geometry?: Record<string, { origin: CadOrigin; origin_text: string; ok: boolean; extents_mm: number[] }>;
}

export interface CatalogList {
  categories: Record<string, string>;
  components: PartSummary[];
  refs: Record<string, RefInfo>;
}

export type CadOrigin = 'manufacturer' | 'reconstructed' | 'bbox' | 'placeholder';

/** A part's geometry (backend builder/cad.py): where it came from and the checks it passed. */
export interface CadEntry {
  component: string;
  origin: CadOrigin;
  origin_text: string;
  file: string;
  source_name: string | null;
  source_url: string | null;
  sha256: string | null;
  imported: string;
  units: string;
  scale: number;
  extents_mm: number[];
  shift_mm: number[];
  volume_mm3: number | null;
  solids: number | null;
  faces: number;
  checks: { name: string; ok: boolean | null; detail: string }[];
  ok: boolean;
  licence: string | null;
}

/** What Send to Optimization wrote (backend builder/send.py; kept as builder.json in the project). */
export interface SentRecord {
  design_id: string;
  design_name: string | null;
  design_version: number | null;
  sent_at: string;
  size: string;
  parts: { part_id: string; name: string; catalog_id: string; slot: string; category: string; origin: CadOrigin; mass_kg: number | null; unit: number }[];
  not_packed: { name: string; slot: string; mass_kg: number; qty: number }[];
  warnings: string[];
  unenforced: string[];
}

export interface SendResult extends SentRecord {
  project: string;
  switched: boolean;
  previous?: string;
}

export interface ProjectInfo {
  name: string;
  parts: number;
  form_factor: string;
  current: boolean;
  modified: number;
  builder: SentRecord | null;
}

export interface CadList {
  origins: Record<CadOrigin, string>;
  items: Record<string, CadEntry>;
  offered: { id: string; name: string; available: string; url: string | null; formats: string[]; note?: string | null }[];
}

export interface SlotInfo {
  id: string;
  label: string;
  categories: string[];
  place: string;
}

/** A number for people: about three significant figures, no exponent below a million. */
export function num(v: unknown): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return v == null ? '—' : String(v);
  const a = Math.abs(v);
  if (a === 0) return '0';
  if (a >= 1e6) return v.toExponential(2);
  if (a >= 1000) return Math.round(v).toLocaleString('en-US');
  if (Number.isInteger(v)) return String(v);
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(3);
}

/** A value with its unit ("°" and "%" stick to the number). */
export function withUnit(v: unknown, unit: string | null | undefined): string {
  if (v == null) return '—';
  const s = num(v);
  if (!unit) return s;
  if (unit === '%' || unit === 'deg') return `${s}${unit === 'deg' ? '°' : ' %'}`;
  return `${s} ${unit}`;
}

/** Whether a calculation meets its requirement: true, false, or null when it cannot be told. */
export function verdict(c: Calc): boolean | null {
  if (c.value == null) return null;
  for (const k of ['ok', 'meets', 'feasible'] as const) {
    if (k in c && c[k] != null) return Boolean(c[k]);
  }
  return null;
}

export const STATUS_TEXT: Record<CheckStatus, string> = {
  compatible: 'Compatible',
  assumptions: 'Compatible with assumptions or modifications',
  incompatible: 'Incompatible',
  unknown: 'Insufficient information to verify',
};

export const PICK_TEXT: Record<PickStatus, string> = {
  recommended: 'Recommended',
  user: 'Your choice',
  none: 'Not needed',
  missing: 'Nothing suitable',
  placeholder: 'Your payload (placeholder)',
};

export function priceText(p: Price): string {
  if (p.value == null) return 'quote required';
  return `${p.value.toLocaleString('en-US')} ${p.currency ?? ''} (listed)`.trim();
}

export function dimsText(d: number[] | null | undefined): string {
  return d ? `${d.map((x) => num(x)).join(' × ')} mm` : 'not published';
}

export function powerText(p: PartSummary['power_w']): string {
  const t = p.typical;
  const pk = p.peak;
  if (t == null && pk == null) return 'not published';
  return [t != null ? `${num(t)} W typical` : null, pk != null ? `${num(pk)} W peak` : null].filter(Boolean).join(', ');
}
