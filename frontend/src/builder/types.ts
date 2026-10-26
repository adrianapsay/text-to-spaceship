// V3 CubeSat Builder: the shapes of /api/builder (backend t2s/builder, api/builder.py).

/** where a requirement's value came from */
export type ReqSource = 'user' | 'statement' | 'default' | 'derived';

export interface Requirement {
  key: string;
  qid: string | null;
  section?: string;
  prompt?: string;
  value: unknown;
  unit: string | null;
  source: ReqSource;
  /** for a default: why it was taken (ASSUMED) */
  note: string;
  /** for a value read from the statement: which words */
  answer_why?: string | null;
  /** the value in words (option labels, units, names) */
  display?: string;
}

export interface BuilderAnswer {
  value: unknown;
  unknown: boolean;
  at: string;
  source: ReqSource;
  why?: string;
}

export interface QuestionOption {
  value: unknown;
  label: string;
  explain: string;
}

export type QuestionKind = 'choice' | 'multi' | 'number' | 'bool' | 'region' | 'station' | 'text';

export interface QuestionView {
  id: string;
  section: string;
  prompt: string;
  help: string;
  kind: QuestionKind;
  key: string;
  unit: string | null;
  min: number | null;
  max: number | null;
  advanced: boolean;
  options: QuestionOption[];
  default: unknown;
  default_why: string;
  answer: BuilderAnswer | null;
}

export interface BuilderDesign {
  id: string;
  name: string;
  created: string;
  updated: string;
  version: number;
  statement: string;
  answers: Record<string, BuilderAnswer>;
  requirements: Record<string, Omit<Requirement, 'key'>>;
  /** the user's own parts per slot (component null: left out); others follow the architect's recommendation */
  selections: Record<string, { component: string | null; qty: number }>;
  /** the trade sliders and the lifetime override */
  prefs?: Record<string, number>;
  /** the CubeSat size the user fixed (else the recommended one) */
  size_u?: number;
  /** each Send to Optimization: the project it made */
  sent?: { project: string; at: string; version: number }[];
  history: { version: number; at: string; what: string }[];
}

export interface BuilderView {
  next: QuestionView | null;
  pending: string[];
  completeness: { answered: number; total: number; complete: boolean };
  requirements: Requirement[];
  sections: Record<string, string>;
}

export interface Finding {
  qid: string;
  value: unknown;
  why: string;
}

export interface BuilderResponse {
  design: BuilderDesign;
  view: BuilderView;
  findings?: Finding[];
}

export interface DesignSummary {
  id: string;
  name: string;
  updated: string;
  version: number;
  mission_type: string | null;
}

export interface Region {
  key: string;
  name: string;
  lat_min?: number;
  lat_max?: number;
  lon_min?: number;
  lon_max?: number;
  source: string;
  note?: string;
}

export interface Station {
  key: string;
  name: string;
  lat: number;
  lon: number;
  alt_m: number;
  min_elev_deg: number;
  source: string;
  note?: string;
}

export interface BuilderMeta {
  regions: Region[];
  stations: Station[];
  sections: Record<string, string>;
  questions: number;
  sliders: Record<string, { label: string; low: string; high: string; default: number }>;
  sizes: number[];
  packed_sizes: number[];
  slots: { id: string; label: string; categories: string[]; place: string }[];
  categories: Record<string, string>;
  engine: string;
}
