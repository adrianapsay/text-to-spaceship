// One formatting function for every number the UI shows (protocol §E.1 / §I.1).
//   mm 0.1 · clearances 0.01 mm · kg 0.001 · kg·m² 3 significant figures (shared column exponent in tables)
//   deg 0.1 · % 0.1 · U+2212 minus sign · U+202F narrow no-break space before units.
// Unknown values (null, undefined, NaN, ±Infinity) are shown as "—".

export const MINUS = '−';
export const NNBSP = ' ';
export const DASH = '—';

export type Quantity =
  | 'mm' // length, 0.1 mm
  | 'clearance' // clearance, 0.01 mm
  | 'kg' // mass, 0.001 kg
  | 'kgm2' // inertia, 3 s.f., e-notation
  | 'deg' // angle, 0.1°
  | 'pct' // fraction 0..1 shown as percent, 0.1 %
  | 'pct100' // value already in percent, 0.1 %
  | 'density' // kg/m³, integer with thousands separators
  | 'mm3' // volume in mm³ shown as cm³, 0.1
  | 'cm3' // volume already in cm³
  | 'rel' // relative cost units, 0.1
  | 's' // seconds, 0.1
  | 'us' // microseconds, 3 s.f.
  | 'int' // integer count
  | 'ratio' // unitless, 3 s.f.
  | 'score' // unitless score, 0.001
  | 'scale'; // size-study scale factor ×1.00

const SUPERSCRIPT: Record<string, string> = {
  '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
  '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '-': '⁻',
};

export function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Replace ASCII hyphen-minus used as a sign with U+2212. */
export function signFix(s: string): string {
  return s.replace(/^-/, MINUS).replace(/e-/g, `e${MINUS}`);
}

function grouped(v: number, decimals: number): string {
  const s = Math.abs(v).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: true,
  });
  return (v < 0 && Number(s.replace(/,/g, '')) !== 0 ? MINUS : '') + s;
}

function fixed(v: number, decimals: number): string {
  const s = Math.abs(v).toFixed(decimals);
  const isZero = Number(s) === 0;
  return (v < 0 && !isZero ? MINUS : '') + s;
}

/** Three significant figures in e-notation with a proper minus, e.g. 1.03e−2. */
export function sig3e(v: number): string {
  if (v === 0) return '0.00';
  const exp = Math.floor(Math.log10(Math.abs(v)));
  let mant = v / 10 ** exp;
  let e = exp;
  if (Math.abs(Number(mant.toFixed(2))) >= 10) {
    mant /= 10;
    e += 1;
  }
  const m = fixed(mant, 2);
  return e === 0 ? m : `${m}e${e < 0 ? MINUS : ''}${Math.abs(e)}`;
}

export function superscript(n: number): string {
  return String(n)
    .split('')
    .map((c) => SUPERSCRIPT[c] ?? c)
    .join('');
}

const UNIT: Record<Quantity, string> = {
  mm: 'mm', clearance: 'mm', kg: 'kg', kgm2: 'kg·m²', deg: '°', pct: '%', pct100: '%', density: 'kg/m³',
  mm3: 'cm³', cm3: 'cm³', rel: 'rel. units', s: 's', us: 'µs', int: '', ratio: '', score: '', scale: '',
};

export interface FmtOptions {
  /** omit the unit (for table cells whose header carries it) */
  unit?: boolean;
  /** prefix "+" on positive values (signed deltas) */
  signed?: boolean;
}

/** Format a value for display. */
export function fmt(value: number | null | undefined, quantity: Quantity, opts: FmtOptions = {}): string {
  if (!isFiniteNumber(value)) return DASH;
  const showUnit = opts.unit !== false;
  let body: string;
  switch (quantity) {
    case 'mm':
      body = fixed(value, 1);
      break;
    case 'clearance':
      body = fixed(value, 2);
      break;
    case 'kg':
      body = fixed(value, 3);
      break;
    case 'kgm2':
      body = sig3e(value);
      break;
    case 'deg':
      body = fixed(value, 1);
      break;
    case 'pct':
      body = fixed(value * 100, 1);
      break;
    case 'pct100':
      body = fixed(value, 1);
      break;
    case 'density':
      body = grouped(value, 0);
      break;
    case 'mm3':
      body = grouped(value / 1000, 1);
      break;
    case 'cm3':
      body = grouped(value, 1);
      break;
    case 'rel':
      body = fixed(value, 1);
      break;
    case 's':
      body = fixed(value, 1);
      break;
    case 'us':
      body = value >= 100 ? grouped(value, 0) : Number(value.toPrecision(3)).toString().replace(/^-/, MINUS);
      break;
    case 'int':
      body = grouped(Math.round(value), 0);
      break;
    case 'ratio':
      body = signFix(Number(value.toPrecision(3)).toString());
      break;
    case 'score':
      body = fixed(value, 3);
      break;
    case 'scale':
      return `×${fixed(value, 2)}`;
  }
  if (opts.signed && value > 0 && Number(body.replace(/[^0-9.]/g, '')) !== 0) body = `+${body}`;
  const unit = UNIT[quantity];
  if (!showUnit || !unit) return body;
  if (unit === '°') return `${body}°`;
  return `${body}${NNBSP}${unit}`;
}

/** Vector of lengths, e.g. "(0.4, −0.2, −55.1) mm". */
export function fmtVec(v: readonly number[] | null | undefined, quantity: Quantity = 'mm'): string {
  if (!v || v.length !== 3 || !v.every(isFiniteNumber)) return DASH;
  const parts = v.map((x) => fmt(x, quantity, { unit: false }));
  const unit = UNIT[quantity];
  return `(${parts.join(', ')})${unit ? NNBSP + unit : ''}`;
}

/** Shared column exponent for a column of inertia-like values (3 significant figures each). */
export function fmtColumn(values: (number | null | undefined)[], unit = 'kg·m²'): { header: string; exponent: number; cells: string[] } {
  const finite = values.filter(isFiniteNumber).map(Math.abs).filter((v) => v > 0);
  const exponent = finite.length ? Math.floor(Math.log10(Math.max(...finite))) : 0;
  const cells = values.map((v) => {
    if (!isFiniteNumber(v)) return DASH;
    if (v === 0) return '0';
    const scaled = v / 10 ** exponent;
    const ownExp = Math.floor(Math.log10(Math.abs(v)));
    const decimals = Math.max(0, Math.min(8, 2 - (ownExp - exponent)));
    return fixed(scaled, decimals);
  });
  const header = exponent === 0 ? `(${unit})` : `(10${superscript(exponent)}${NNBSP}${unit})`;
  return { header, exponent, cells };
}

export type Direction = 'lower' | 'higher';

/** Signed delta with words: "−1.3 mm better". Lower is better unless direction = 'higher'. */
export function fmtDelta(
  delta: number | null | undefined,
  quantity: Quantity,
  direction: Direction = 'lower',
  epsilon = 0,
): { text: string; verdict: 'better' | 'worse' | 'unchanged' | 'unknown' } {
  if (!isFiniteNumber(delta)) return { text: DASH, verdict: 'unknown' };
  const shown = fmt(delta, quantity, { signed: true });
  const zero = fmt(0, quantity);
  if (Math.abs(delta) <= epsilon || shown.replace(/^[+−]/, '') === zero) return { text: `${zero} unchanged`, verdict: 'unchanged' };
  const better = direction === 'lower' ? delta < 0 : delta > 0;
  return { text: `${shown} ${better ? 'better' : 'worse'}`, verdict: better ? 'better' : 'worse' };
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}
