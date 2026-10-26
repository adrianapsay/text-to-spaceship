// One vanilla zustand store = the single source of truth. Separate slices:
//   dataset  – project + parts as the backend reported them
//   physical – the user's physical edits (mass, lock): "changes the physics"
//   goals    – goal sliders / settings: "never changes the parts"
//   solver   – layouts, run status, selector, studies (driven by the WebSocket)
//   view     – UI-only state
//   conn     – transport / protocol bookkeeping
// Physical and goal edits never touch each other's slice (test T-UI4).

import { createStore, type StoreApi } from 'zustand/vanilla';
import { useStore } from 'zustand';
import type { Envelope, Mat3, Part, ProjectSnapshot, Settings, SliderKey } from '../api/types';
import type { TransportMode } from '../api/transport';
import type { WsState } from '../api/ws';
import {
  connOnNewConnection,
  initialConn,
  initialSolver,
  markClientSeqSent,
  maxRevs,
  reduceEnvelope,
  type ConnProto,
  type Effect,
  type SolverState,
} from '../api/protocol';
import { normaliseRotations } from '../lib/math3';
import { applyPreset, detectPreset, type PresetId } from './presets';

export type TabId =
  | 'builder'
  | 'overview'
  | 'components'
  | 'optimization'
  | 'physics'
  | 'comparison'
  | 'size'
  | 'explain'
  | 'engineering'
  | 'hardware'
  | 'bom'
  | 'drawings'
  | 'manufacturable'
  | 'cad'
  | 'results';

export type ColorMode = 'subsystem' | 'status' | 'mass' | 'displacement';

export interface DatasetSlice {
  project: ProjectSnapshot | null;
  parts: Record<string, Part>;
  partOrder: string[];
  rotations: Mat3[];
  unitsQueue: string[];
  uploading: number;
  error: string | null;
}

export interface MassEdit {
  mass_kg: number;
  client_seq: number | null;
  committed: boolean;
}

export interface PhysicalSlice {
  massEdits: Record<string, MassEdit>;
  lockEdits: Record<string, { locked: boolean; client_seq: number | null }>;
}

export interface GoalsSlice {
  settings: Settings | null;
  preset: PresetId;
  /** client_seq of the newest settings edit not yet acknowledged (null when in sync) */
  pendingSeq: number | null;
  dragging: SliderKey | null;
}

export interface ViewSlice {
  tab: TabId;
  expert: boolean;
  selectedPartId: string | null;
  hoveredPartId: string | null;
  hidden: string[];
  isolated: string | null;
  colorMode: ColorMode;
  showEnclosure: boolean;
  showLabels: boolean;
  showCom: boolean;
  showAxes: boolean;
  showBBoxes: boolean;
  showGhost: boolean;
  linkCameras: boolean;
  showMovement: boolean;
  announce: string;
  fitRequest: number;
  explainSection: 'map' | 'proof' | 'selector';
  /** exploded view, 0 (assembled) … 100 (parts pulled apart); display only */
  explode: number;
}

export interface ConnSlice extends ConnProto {
  mode: TransportMode | 'unknown';
  modeReason: string;
  wsState: WsState;
  backendVersion: string | null;
  lastMessageAt: string | null;
  reconnectAttempt: number;
  nextRetryMs: number | null;
  backendDetected: boolean;
}

export interface AppState {
  dataset: DatasetSlice;
  physical: PhysicalSlice;
  goals: GoalsSlice;
  solver: SolverState;
  view: ViewSlice;
  conn: ConnSlice;
}

export interface AppActions {
  // dataset
  loadProject(p: ProjectSnapshot): void;
  upsertParts(parts: Part[]): void;
  removePartLocal(id: string): void;
  enqueueUnits(ids: string[]): void;
  dequeueUnits(id: string): void;
  setUploading(delta: number): void;
  setDatasetError(msg: string | null): void;
  // physical
  setMassEdit(id: string, mass: number, clientSeq: number | null, committed: boolean): void;
  clearMassEdit(id: string): void;
  setLockEdit(id: string, locked: boolean, clientSeq: number | null): void;
  // goals
  setSlider(key: SliderKey, value: number): void;
  setPreset(p: PresetId): void;
  setStage(stage: 1 | 2): void;
  setGoalSettings(s: Settings): void;
  setPendingSettingsSeq(seq: number | null): void;
  setDragging(k: SliderKey | null): void;
  // solver + conn
  applyEnvelope(env: Envelope): Effect[];
  newConnection(): void;
  markSent(clientSeq: number): void;
  setWsState(s: WsState, attempt: number, nextRetryMs: number | null): void;
  setMode(mode: TransportMode, reason: string, version?: string | null): void;
  setBackendDetected(v: boolean): void;
  // view
  setTab(t: TabId): void;
  setExpert(v: boolean): void;
  select(id: string | null): void;
  hover(id: string | null): void;
  toggleHidden(id: string): void;
  hideOthers(id: string): void;
  isolate(id: string | null): void;
  showAll(): void;
  setColorMode(m: ColorMode): void;
  setViewFlag(k: 'showEnclosure' | 'showLabels' | 'showCom' | 'showAxes' | 'showBBoxes' | 'showGhost' | 'linkCameras' | 'showMovement', v: boolean): void;
  announce(text: string): void;
  requestFit(): void;
  setExplainSection(s: ViewSlice['explainSection']): void;
  setExplode(v: number): void;
}

export type AppStore = StoreApi<AppState & AppActions>;

const PREF_KEY = 't2s.prefs.v1';
function loadPrefs(): Partial<Pick<ViewSlice, 'expert' | 'colorMode'>> {
  try {
    const raw = globalThis.localStorage?.getItem(PREF_KEY);
    return raw ? (JSON.parse(raw) as Partial<Pick<ViewSlice, 'expert' | 'colorMode'>>) : {};
  } catch {
    return {};
  }
}
function savePrefs(v: Pick<ViewSlice, 'expert' | 'colorMode'>) {
  try {
    globalThis.localStorage?.setItem(PREF_KEY, JSON.stringify(v));
  } catch {
    /* storage unavailable: preference is a convenience only */
  }
}

export function initialState(): AppState {
  const prefs = loadPrefs();
  return {
    dataset: { project: null, parts: {}, partOrder: [], rotations: [], unitsQueue: [], uploading: 0, error: null },
    physical: { massEdits: {}, lockEdits: {} },
    goals: { settings: null, preset: 'balanced', pendingSeq: null, dragging: null },
    solver: initialSolver(),
    view: {
      tab: 'overview',
      expert: prefs.expert ?? false,
      selectedPartId: null,
      hoveredPartId: null,
      hidden: [],
      isolated: null,
      colorMode: prefs.colorMode ?? 'subsystem',
      showEnclosure: true,
      showLabels: false,
      showCom: true,
      showAxes: false,
      showBBoxes: false,
      showGhost: true,
      linkCameras: true,
      showMovement: true,
      announce: '',
      fitRequest: 0,
      explainSection: 'map',
      explode: 0,
    },
    conn: {
      ...initialConn(),
      mode: 'unknown',
      modeReason: '',
      wsState: 'idle',
      backendVersion: null,
      lastMessageAt: null,
      reconnectAttempt: 0,
      nextRetryMs: null,
      backendDetected: false,
    },
  };
}

export function createAppStore(init: Partial<AppState> = {}): AppStore {
  return createStore<AppState & AppActions>()((set, get) => ({
    ...initialState(),
    ...init,

    // ------------------------------------------------------------------ dataset
    loadProject(raw) {
      // tolerate partial snapshots (missing arrays / revs) from an early backend
      const p: ProjectSnapshot = {
        ...raw,
        parts: raw.parts ?? [],
        rotations: raw.rotations ?? [],
        limits: raw.limits ?? {},
        enclosure: raw.enclosure ?? {},
        revs: { ...{ epoch: 0, parts_rev: 0, constraint_rev: 0, mass_rev: 0, weights_rev: 0 }, ...((raw.revs as Partial<ProjectSnapshot['revs']> | undefined) ?? {}) },
      };
      const parts = Object.fromEntries(p.parts.map((x) => [x.id, x]));
      const s = get();
      // pending settings edits survive a project reload (they are re-sent); otherwise adopt the server's settings
      const settings = s.goals.pendingSeq !== null && s.goals.settings ? s.goals.settings : p.settings;
      // physical edits the server has applied (per applied_client_seq) are dropped: the part record now carries them
      const applied = s.conn.appliedClientSeq;
      const massEdits = Object.fromEntries(
        Object.entries(s.physical.massEdits).filter(([id, e]) => parts[id] && (e.client_seq === null || e.client_seq > applied)),
      );
      const lockEdits = Object.fromEntries(
        Object.entries(s.physical.lockEdits).filter(([id, e]) => parts[id] && (e.client_seq === null || e.client_seq > applied)),
      );
      const unitsQueue = Array.from(
        new Set([...s.dataset.unitsQueue.filter((id) => parts[id]?.status === 'NEEDS_UNITS'), ...p.parts.filter((x) => x.status === 'NEEDS_UNITS').map((x) => x.id)]),
      );
      set({
        dataset: { ...s.dataset, project: p, parts, partOrder: p.parts.map((x) => x.id), rotations: normaliseRotations(p.rotations), unitsQueue, error: null },
        physical:
          Object.keys(massEdits).length === Object.keys(s.physical.massEdits).length &&
          Object.keys(lockEdits).length === Object.keys(s.physical.lockEdits).length
            ? s.physical
            : { massEdits, lockEdits },
        goals: !settings || settings === s.goals.settings ? s.goals : { ...s.goals, settings, preset: detectPreset(settings.sliders, settings.stage) },
        conn: { ...s.conn, newest: maxRevs(s.conn.newest, p.revs) },
        view: s.view.selectedPartId && !parts[s.view.selectedPartId] ? { ...s.view, selectedPartId: null } : s.view,
      });
    },
    upsertParts(list) {
      const d = get().dataset;
      const parts = { ...d.parts };
      const order = d.partOrder.slice();
      for (const p of list) {
        if (!parts[p.id]) order.push(p.id);
        parts[p.id] = p;
      }
      const unitsQueue = Array.from(new Set([...d.unitsQueue, ...list.filter((p) => p.status === 'NEEDS_UNITS').map((p) => p.id)])).filter(
        (id) => parts[id]?.status === 'NEEDS_UNITS',
      );
      set({ dataset: { ...d, parts, partOrder: order, unitsQueue } });
    },
    removePartLocal(id) {
      const d = get().dataset;
      const parts = { ...d.parts };
      delete parts[id];
      set({ dataset: { ...d, parts, partOrder: d.partOrder.filter((x) => x !== id), unitsQueue: d.unitsQueue.filter((x) => x !== id) } });
    },
    enqueueUnits(ids) {
      const d = get().dataset;
      set({ dataset: { ...d, unitsQueue: Array.from(new Set([...d.unitsQueue, ...ids])) } });
    },
    dequeueUnits(id) {
      const d = get().dataset;
      set({ dataset: { ...d, unitsQueue: d.unitsQueue.filter((x) => x !== id) } });
    },
    setUploading(delta) {
      const d = get().dataset;
      set({ dataset: { ...d, uploading: Math.max(0, d.uploading + delta) } });
    },
    setDatasetError(msg) {
      set({ dataset: { ...get().dataset, error: msg } });
    },

    // ------------------------------------------------------------------ physical (changes the physics)
    setMassEdit(id, mass, clientSeq, committed) {
      const ph = get().physical;
      set({ physical: { ...ph, massEdits: { ...ph.massEdits, [id]: { mass_kg: mass, client_seq: clientSeq, committed } } } });
    },
    clearMassEdit(id) {
      const ph = get().physical;
      if (!ph.massEdits[id]) return;
      const massEdits = { ...ph.massEdits };
      delete massEdits[id];
      set({ physical: { ...ph, massEdits } });
    },
    setLockEdit(id, locked, clientSeq) {
      const ph = get().physical;
      set({ physical: { ...ph, lockEdits: { ...ph.lockEdits, [id]: { locked, client_seq: clientSeq } } } });
    },

    // ------------------------------------------------------------------ goals (never changes the parts)
    setSlider(key, value) {
      const g = get().goals;
      if (!g.settings) return;
      const v = Math.max(0, Math.min(100, Math.round(value)));
      const sliders = { ...g.settings.sliders, [key]: v };
      const settings = { ...g.settings, sliders };
      set({ goals: { ...g, settings, preset: detectPreset(sliders, settings.stage) } });
    },
    setPreset(p) {
      const g = get().goals;
      if (!g.settings) return;
      const sliders = applyPreset(g.settings.sliders, p, g.settings.stage);
      set({ goals: { ...g, settings: { ...g.settings, sliders }, preset: p } });
    },
    setStage(stage) {
      const g = get().goals;
      if (!g.settings) return;
      set({ goals: { ...g, settings: { ...g.settings, stage }, preset: detectPreset(g.settings.sliders, stage) } });
    },
    setGoalSettings(s) {
      const g = get().goals;
      set({ goals: { ...g, settings: s, preset: detectPreset(s.sliders, s.stage) } });
    },
    setPendingSettingsSeq(seq) {
      set({ goals: { ...get().goals, pendingSeq: seq } });
    },
    setDragging(k) {
      set({ goals: { ...get().goals, dragging: k } });
    },

    // ------------------------------------------------------------------ solver / conn
    applyEnvelope(env) {
      const s = get();
      const r = reduceEnvelope(s.conn, s.solver, env);
      if (!r.accepted) return [];
      const conn = { ...s.conn, ...r.conn, lastMessageAt: new Date().toISOString() };
      let goals = s.goals;
      if (goals.pendingSeq !== null && conn.appliedClientSeq >= goals.pendingSeq) goals = { ...goals, pendingSeq: null };
      set({ conn, solver: r.solver, goals });
      return r.effects;
    },
    newConnection() {
      const c = get().conn;
      set({ conn: { ...c, ...connOnNewConnection(c) } });
    },
    markSent(clientSeq) {
      const c = get().conn;
      set({ conn: { ...c, ...markClientSeqSent(c, clientSeq) } });
    },
    setWsState(wsState, attempt, nextRetryMs) {
      set({ conn: { ...get().conn, wsState, reconnectAttempt: attempt, nextRetryMs } });
    },
    setMode(mode, reason, version = null) {
      set({ conn: { ...get().conn, mode, modeReason: reason, backendVersion: version } });
    },
    setBackendDetected(v) {
      set({ conn: { ...get().conn, backendDetected: v } });
    },

    // ------------------------------------------------------------------ view
    setTab(tab) {
      set({ view: { ...get().view, tab } });
    },
    setExpert(expert) {
      const v = { ...get().view, expert };
      savePrefs({ expert, colorMode: v.colorMode });
      set({ view: v });
    },
    select(id) {
      const v = get().view;
      if (v.selectedPartId === id) return;
      const name = id ? get().dataset.parts[id]?.name ?? id : null;
      set({ view: { ...v, selectedPartId: id, announce: name ? `Selected ${name}` : 'Selection cleared' } });
    },
    hover(id) {
      const v = get().view;
      if (v.hoveredPartId !== id) set({ view: { ...v, hoveredPartId: id } });
    },
    toggleHidden(id) {
      const v = get().view;
      const hidden = v.hidden.includes(id) ? v.hidden.filter((x) => x !== id) : [...v.hidden, id];
      set({ view: { ...v, hidden } });
    },
    hideOthers(id) {
      const v = get().view;
      set({ view: { ...v, hidden: get().dataset.partOrder.filter((x) => x !== id), isolated: null } });
    },
    isolate(id) {
      const v = get().view;
      set({ view: { ...v, isolated: v.isolated === id ? null : id } });
    },
    showAll() {
      set({ view: { ...get().view, hidden: [], isolated: null } });
    },
    setColorMode(colorMode) {
      const v = { ...get().view, colorMode };
      savePrefs({ expert: v.expert, colorMode });
      set({ view: v });
    },
    setViewFlag(k, val) {
      set({ view: { ...get().view, [k]: val } });
    },
    announce(text) {
      set({ view: { ...get().view, announce: text } });
    },
    requestFit() {
      const v = get().view;
      set({ view: { ...v, fitRequest: v.fitRequest + 1 } });
    },
    setExplainSection(explainSection) {
      set({ view: { ...get().view, explainSection } });
    },
    setExplode(v) {
      set({ view: { ...get().view, explode: Math.max(0, Math.min(100, Math.round(v))) } });
    },
  }));
}

export const appStore: AppStore = createAppStore();

export function useApp<T>(selector: (s: AppState & AppActions) => T): T {
  return useStore(appStore, selector);
}

/** Display mass of a part: the user's pending physical edit, else the backend value. */
export function displayMass(s: AppState, id: string): number | null {
  return s.physical.massEdits[id]?.mass_kg ?? s.dataset.parts[id]?.mass_kg ?? null;
}

export function partList(s: AppState): Part[] {
  return s.dataset.partOrder.map((id) => s.dataset.parts[id]).filter(Boolean);
}
