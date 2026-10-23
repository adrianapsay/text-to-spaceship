// Wire types for docs/api-contract.md (v1). Field names are snake_case exactly as on the wire.
// Fields the contract does not define but the front end can use when present are marked "optional extension";
// every such field is listed in frontend/DECISIONS.md.

export type Vec3 = [number, number, number];
export type Mat3 = [Vec3, Vec3, Vec3];

export type PartStatus = 'VALID' | 'REPAIRED' | 'WITHHELD' | 'NEEDS_UNITS' | 'ANALYSING';
export type MassSource = 'ASSUMED' | 'USER_MASS' | 'USER_DENSITY' | 'WITHHELD';
export type Subsystem = 'power' | 'electronics' | 'adcs' | 'tanks' | 'payload' | 'structure' | 'unknown';
export type Units = 'mm' | 'cm' | 'm' | 'in';

export interface Part {
  id: string;
  name: string;
  file: string;
  sha256: string;
  units: Units | string;
  units_confirmed: boolean;
  status: PartStatus;
  status_detail: string;
  repairs: string[];
  triangles: number;
  display_triangles: number;
  subsystem: Subsystem | string;
  labels: string[];
  extents_mm: Vec3;
  volume_mm3: number | null;
  density_kg_m3: number | null;
  mass_kg: number | null;
  mass_source: MassSource;
  com_canonical_mm: Vec3 | null;
  inertia_com_kgm2: Mat3 | null;
  principal_kgm2: Vec3 | null;
  solidity: number | null;
  obb_fill: number | null;
  allowed_orients: number[];
  locked: boolean;
  lock_pose: Pose | null;
  tags: string[];
}

export interface Pose {
  part_id: string;
  orient: number;
  t_um: Vec3;
}

export type LayoutStatus = 'CANDIDATE' | 'VALIDATING' | 'VALIDATED' | 'REJECTED' | 'STALE' | 'FINAL' | 'INFEASIBLE';
export type LayoutMode = 'default' | 'continuous_cable' | 'manufacturable';
export type ExtraProcess = 'metal_am' | 'sheet' | 'machined' | 'catalogue' | 'direct' | 'card_guide' | 'standoff';

export interface ExtraItem {
  id: string;
  kind: string;
  process: ExtraProcess | string;
  for_part: string;
  mesh_url: string;
  mass_kg: number | null;
  cost_rel: number | null;
  /** optional extension */
  material?: string;
  /** optional extension */
  label?: string;
  /** V2 Stage 2 bracket: direct | machined | sheet | clamp | cradle | metal_am */
  bracket_kind?: string;
  /** V2: false = mass estimated from the reserved box (cradle / metal-AM bracket not designed yet) */
  exact?: boolean;
  /** V2: the reserved box (lo xyz, hi xyz) */
  box_mm?: number[];
  target?: string;
}

/** V2 Stage 2: one modelled bracket. Its reserved box is part of the packing and of the fit proof (Lemma 4). */
export interface BracketInfo {
  name: string;
  pid: string;
  kind: string;
  mount_type: string;
  process: string;
  fasteners: number;
  gap_mm: number;
  target: string;
  reserve: number[];
  depth_mm: number;
  mass_kg: number;
  cost_rel: number;
  material: string;
  label: string;
  exact: boolean;
}

/** V2: a cradle / metal-AM bracket designed by the generative-design winner and checked with two FEA solvers */
export interface BracketDesign {
  pid: string;
  generator: string;
  mass_kg: number;
  cost_rel: number;
  label: string;
  passed: boolean;
  reason: string;
  sigma_mpa: number | null;
  ms_yield: number | null;
  ms_ult: number | null;
  f1_hz: number | null;
  /** natural modes (Rayleigh–Ritz, part at its CG), lowest first */
  modes?: BracketMode[] | null;
  agreement?: Record<string, number | null>;
  solvers?: Record<string, { solver: string; f1_hz: number | null; seconds: number }>;
  fallback?: string | null;
}

export interface BracketMode {
  f_hz: number;
  /** effective-mass fraction along x, y, z */
  eff_mass_frac: [number, number, number];
  /** e.g. "part rotates about x", "part moves along y" */
  motion: string;
}

/** V2: generative-design contest results (endpoint /api/gd/contest) */
export interface ContestRow {
  problem: string;
  generator: string;
  ok: boolean;
  passed: boolean;
  reason: string;
  mass_g: number | null;
  /** von Mises averaged over each design voxel (used for the margins) */
  sigma_mpa: number | null;
  /** raw nodal peak at sharp corners: grows with mesh refinement, reported only */
  sigma_peak_mpa?: number | null;
  ms_yield: number | null;
  ms_ult: number | null;
  f1_hz: number | null;
  modes?: BracketMode[] | null;
  max_disp_mm: number | null;
  gen_seconds: number | null;
  fea_seconds: number | null;
  overhang_fraction: number | null;
  agreement?: Record<string, number | null>;
}

/** V2 "Find largest size that fits" (endpoint /api/studies/largest-size): search-based bisection */
export interface LargestSize {
  status: string;
  largest_pct: number | null;
  verdict?: string;
  note?: string;
  progress?: number;
  detail?: string;
  rows: { pct: number; found: boolean; search_feasible: boolean; certified: boolean; cv: number; unmounted: number; seconds: number }[];
}

export interface ContestResults {
  created: string;
  status: string;
  criteria: string[];
  problems: { name: string; description: string; part_mass_kg: number; reserve_mm: number[] }[];
  entrants: { name: string; source: string; available: boolean; note?: string }[];
  rows: ContestRow[];
  standings: { generator: string; passed: number; problems: number; total_mass_g: number | null; rank: number }[];
  winner: { generator: string; why: string } | null;
}

export interface Metrics {
  length_used_mm?: number | null;
  span_mm?: number | null;
  space_used?: number | null;
  largest_empty_box_mm?: Vec3 | null;
  mass_kg?: number | null;
  com_mm?: Vec3 | null;
  com_error_mm?: number | null;
  com_box_ok?: boolean | null;
  com_box_margin_mm?: Vec3 | null;
  inertia_kgm2?: Mat3 | null;
  principal_kgm2?: Vec3 | null;
  principal_axes?: Mat3 | null;
  lambda_max_kgm2?: number | null;
  trace_kgm2?: number | null;
  products_norm_kgm2?: number | null;
  kappa?: number | null;
  tilt_deg?: number | null;
  min_clearance_mm?: number | null;
  margin_objective?: number | null;
  cable_blocked_fraction?: number | null;
  hardware_cost_rel?: number | null;
  insertion_order?: string[] | null;
  interlocked?: [string, string][] | null;
  /** V2: optional parts this layout left out (they did not fit) */
  optional_left_out?: string[] | null;
}

export type ScoreKey = 'L' | 'D' | 'I' | 'G' | 'H' | 'C' | 'O';

export interface Scores {
  normalised: Partial<Record<ScoreKey, number | null>>;
  g: number | null;
  norm_epoch: number | null;
}

export interface AlgorithmRef {
  id: string;
  label: string;
  reason?: string;
}

export interface Validation {
  certified: boolean;
  validator_version: string;
  tolerance_mm: number | null;
  pairs: number | null;
  checked_at: string | null;
}

/** optional extension: backend collision / clearance verdicts for display */
export interface Violation {
  a: string;
  b: string;
  kind: 'clearance' | 'overlap';
  distance_mm: number;
  required_mm?: number;
  points?: [Vec3, Vec3];
}

export interface Layout {
  id: string;
  hash: string;
  stage: 1 | 2;
  mode: LayoutMode | string;
  status: LayoutStatus;
  parts_rev: number;
  constraint_rev: number;
  mass_rev: number;
  weights_rev: number;
  poses: Pose[];
  extra_items: ExtraItem[];
  metrics: Metrics | null;
  scores: Scores | null;
  algorithm: AlgorithmRef | null;
  validation: Validation | null;
  origin: 'archive' | 'search' | 'user' | 'import' | string;
  created: string;
  /** optional extension */
  violations?: Violation[];
  /** Stage 2: "ENGINEERING-CONSTRAINED — not flight-qualified" */
  label?: string;
  /** Stage 2 INFEASIBLE: "NO FEASIBLE LAYOUT FOUND (not proven infeasible)" */
  verdict?: string;
  /** Stage 2: engineering rules this layout breaks (empty when feasible) */
  violations_engineering?: string[];
  /** Stage 2: the rules this layout was decoded under */
  stage2?: Stage2View;
  /** V2 part-size slider: the factor (0.5 … 1) every part was scaled by in this layout; absent = 1 */
  part_scale?: number;
  /** mock fixtures only */
  mock?: boolean;
}

export interface Stage2View {
  mode: string | null;
  corridor: string | null;
  stack_span_mm: [number, number] | null;
  overflow_mm: number | null;
  unmounted: string[];
  mounts: Record<string, { ok: boolean; how: string }>;
  cable_blocked_fraction: number | null;
  frame: FrameBox[];
  insertion_order: string[] | null;
  com_shift_mm?: number | null;
  com_z_unshifted_mm?: number | null;
  /** V2 Stage 2 brackets and their relative cost */
  brackets?: BracketInfo[];
  hardware_cost_rel?: number | null;
  bracket_designs?: Record<string, BracketDesign>;
  assumed: string[];
}

export type SliderKey =
  | 'space'
  | 'balance'
  | 'inertia'
  | 'feasibility'
  | 'mass_symmetry'
  | 'cable'
  | 'cost'
  | 'speed_quality'
  | 'bracket_budget'
  | 'optional_parts';
export type Sliders = Record<SliderKey, number>;

export interface Settings {
  stage: 1 | 2;
  sliders: Sliders;
  target_com_mm: Vec3;
  compactness_definition: 'one_end' | 'span';
  show_frame_mass_in_com: boolean;
  /** V2 part-size slider (Stage 2): 50 … 100 % of full size */
  part_scale_pct?: number;
  /** V2: CubeSat size (CDS Rev 14.1): 3U 100 × 100 × 340.5, 6U 226.3 × 100 × 366, 12U 226.3 × 226.3 × 366 mm */
  form_factor?: '3U' | '6U' | '12U';
  /** V2: design the metal-AM / cradle / clamp brackets of the best Stage 2 layout when the search pauses (default on) */
  auto_design_brackets?: boolean;
}

export interface Revs {
  epoch: number;
  parts_rev: number;
  constraint_rev: number;
  mass_rev: number;
  weights_rev: number;
}

export interface Enclosure {
  size_mm?: Vec3;
  min_mm?: Vec3;
  max_mm?: Vec3;
  form?: string;
  [k: string]: unknown;
}

export interface FrameBox {
  kind: string;
  id?: string;
  min: Vec3;
  max: Vec3;
}

export interface Stage2Frame {
  status?: string;
  wall_mm?: number;
  inner_box_mm?: Vec3;
  rail_mm?: [number, number];
  boxes?: FrameBox[];
  walls?: { inner_min: Vec3; inner_max: Vec3 };
  [k: string]: unknown;
}

export interface Limits {
  com_box_mm?: Vec3;
  cds_mass_note_kg?: number;
  clearance_part_mm?: number;
  clearance_wall_mm?: number;
  length_mm?: number;
  cable_mode_threshold?: number;
  [k: string]: unknown;
}

export interface ProjectSnapshot {
  name: string;
  enclosure: Enclosure;
  rotations: number[][][] | number[][];
  parts: Part[];
  settings: Settings;
  stage2_frame: Stage2Frame | null;
  limits: Limits;
  revs: Revs;
  mock?: boolean;
  dataset_sha256?: string;
}

export type RunStatus = 'IDLE' | 'SEARCHING' | 'CONVERGED' | 'PAUSED' | 'REVALIDATING' | 'ERROR';
export type RunAction = 'start' | 'pause' | 'resume' | 'reset' | 'rerun';

export interface SelectorEvidence {
  [k: string]: unknown;
}

export interface SelectorChoice {
  algorithm: AlgorithmRef | string | null;
  reasons: string[];
  evidence?: SelectorEvidence[];
  mock?: boolean;
}

export interface SelectorSweep {
  slider: SliderKey | string;
  values: number[];
  choices: string[];
  legend: Record<string, string>;
  mock?: boolean;
}

export interface SelectorMap {
  x: string;
  y: string;
  n: number;
  /** grid[row = y index][col = x index] */
  grid: string[][];
  values?: number[];
  legend?: Record<string, string>;
  mock?: boolean;
}

export interface IdeaNode {
  id: string;
  label: string;
  kind: string;
  tab: string | null;
  detail: string | null;
}
export interface IdeaEdge {
  from: string;
  to: string;
  label: string | null;
}
export interface IdeaMap {
  nodes: IdeaNode[];
  edges: IdeaEdge[];
  mock?: boolean;
}

export interface ParetoPoint {
  layout_id: string;
  L: number;
  D: number;
  I: number;
  [k: string]: unknown;
}
export interface Pareto {
  points: ParetoPoint[];
  hv: number | null;
  norm_epoch: number | null;
  mock?: boolean;
}

export interface Proof {
  markdown: string;
  certificate: unknown;
  mock?: boolean;
}

export interface CadStatus {
  status: string;
  detail: string;
}

export interface LayoutSummary {
  id: string;
  hash?: string;
  stage: 1 | 2;
  mode?: string;
  status: LayoutStatus;
  parts_rev: number;
  constraint_rev: number;
  mass_rev?: number;
  weights_rev?: number;
  metrics: Metrics | null;
  scores?: Scores | null;
  algorithm?: AlgorithmRef | null;
  origin?: string;
  created?: string;
  part_ids?: string[];
}

// ---- detail ladder (Addendum 4)
export type FidelityStatus = 'PENDING' | 'RUNNING' | 'DONE';
export interface FidelityAlgoResult {
  length_used_mm: number | null;
  com_error_mm: number | null;
  score_g: number | null;
  first_valid_s: number | null;
  false_reject_rate: number | null;
}
export interface FidelityLevel {
  level: string;
  family: string;
  label: string;
  params: Record<string, unknown> | null;
  proxy_volume_mm3: number | null;
  overhead: number | null;
  build_s: number | null;
  eval_us_median: number | null;
  results: Record<string, FidelityAlgoResult>;
}
export interface FidelityResult {
  status: FidelityStatus;
  levels: FidelityLevel[];
  chosen: Record<string, string>;
  reasons: Record<string, string>;
  stop_reason: 'converged' | 'time_budget' | 'max_level' | null;
  mock?: boolean;
  mock_note?: string;
}
export interface FidelitySummary {
  parts: { part_id: string; name: string; chosen: Record<string, string> }[];
  mock?: boolean;
}

// ---- studies (shapes not fixed by the contract; the UI renders what is present, see DECISIONS.md)
export interface SizeStudyRow {
  scale: number;
  algorithm: string;
  length_used_mm: number | null;
  feasible: boolean;
  layout_id?: string | null;
  com_error_mm?: number | null;
  lambda_max_kgm2?: number | null;
  seed?: number | null;
}
export interface SizeStudy {
  status: string;
  stage?: number;
  stop_reason?: string | null;
  algorithms?: { id: string; label: string }[];
  results?: SizeStudyRow[];
  max_scale?: Record<string, number | null>;
  bounds?: { id: string; label: string; kind?: string; coeff_mm?: number; exponent?: number; max_scale?: number }[];
  winners?: { scale: number; algorithm: string; layout_id: string | null }[];
  progress?: number | null;
}

export interface BenchmarkRow {
  algorithm: string;
  seed: number;
  L: number | null;
  D: number | null;
  I: number | null;
  runtime_s?: number | null;
  hv?: number | null;
  [k: string]: unknown;
}
export interface Benchmarks {
  status: string;
  rows?: BenchmarkRow[];
  curves?: Record<string, { t: number[]; median: number[]; q1: number[]; q3: number[] }>;
  hv_table?: { algorithm: string; hv: number | null; igd_plus?: number | null; n?: number }[];
  algorithms?: { id: string; label: string }[];
}

export interface MfgItem {
  id: string;
  for_part: string;
  part_name?: string;
  mount_type: string;
  process: ExtraProcess | string;
  material?: string | null;
  mass_kg?: number | null;
  cost_rel?: number | null;
  fasteners?: number | null;
  label?: string | null;
  item_id?: string | null;
}
export interface MfgBracketCheck {
  item_id: string;
  ok: boolean;
  min_clearance_mm: number | null;
}
export interface MfgRule {
  item_id: string;
  rule: string;
  value: number | string | null;
  limit: number | string | null;
  pass: boolean;
}
export interface MfgResult {
  status: string;
  algorithm?: AlgorithmRef | null;
  layout_id?: string | null;
  items?: MfgItem[];
  am_rules?: MfgRule[];
  total_cost_rel?: number | null;
  exports?: { kind: string; url: string; label: string; metal_am?: boolean }[];
  detail?: string;
  label?: string;
  mode?: string;
  seconds?: number;
  evaluations?: number;
  feasible?: boolean;
  verdict?: string | null;
  violations?: string[];
  hardware_mass_kg?: number | null;
  bracket_reach_mm?: number;
  validation?: {
    parts_valid: boolean;
    pairs: number;
    statics: number;
    violations: unknown[];
    brackets: MfgBracketCheck[];
    relaxed_rules: boolean;
  };
}

// ---- free-rotation experiment (Stage 1, research; endpoint /api/experiments/free-rotation)
export interface FreeRotationResult {
  status: 'RUNNING' | 'DONE' | 'ERROR' | 'STOPPED' | string;
  detail?: string;
  label?: string;
  method?: string;
  start_layout_id?: string;
  start_length_mm?: number;
  length_used_mm?: number | null;
  improvement_mm?: number | null;
  valid?: boolean;
  min_distance_mm?: number | null;
  seconds?: number;
  rounds?: number;
  accepted_moves?: number;
  exact_checks?: number;
  rotated?: { part_id: string; name?: string; angle_deg: number }[];
  history?: { t_s: number; length_mm: number }[];
}

// ---- Stage 2 constraint attribution (protocol §O.3; endpoint /api/stage2/attribution)
export interface AttributionRow {
  relaxed: string;
  label: string;
  cv: number;
  feasible: boolean;
  length_used_mm: number | null;
  overflow_mm: number | null;
  unmounted: number;
  unplaced: number;
  com_error_mm: number | null;
  evaluations: number;
  seconds: number;
  delta_length_used_mm?: number;
  delta_overflow_mm?: number;
  delta_com_error_mm?: number;
  delta_cv?: number;
}
export interface Attribution {
  status: string;
  mode?: string;
  seed?: number;
  generations?: number;
  population?: number;
  rows: AttributionRow[];
  progress?: number;
  note?: string;
  largest_effect?: { family: string; label: string; text: string };
}

// ---- WebSocket envelope
export interface Envelope<T = unknown> {
  v: 1;
  type: string;
  seq: number;
  epoch: number;
  parts_rev: number;
  constraint_rev: number;
  mass_rev: number;
  weights_rev: number;
  applied_client_seq: number;
  ts: string;
  payload: T;
}

export interface ProgressPayload {
  status: RunStatus | string;
  evaluations: number | null;
  best_g: number | null;
  elapsed_s: number | null;
  islands?: unknown[];
}

export interface SnapshotPayload {
  project: ProjectSnapshot;
  best_validated: Layout | null;
  candidate: Layout | null;
  run_status: RunStatus | string;
  selector: SelectorChoice | null;
  /** Stage 2 without a feasible layout: the least-violating certified candidate */
  least_violating?: Layout | null;
}

export interface StudyUpdatePayload {
  study: 'size' | 'benchmark' | 'mfg' | 'fidelity' | string;
  progress: number | null;
  partial: unknown;
}
