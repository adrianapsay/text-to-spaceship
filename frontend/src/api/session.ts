// Session controller: wires the store to the REST + WebSocket clients and owns all side effects.
//  * goal edits  → `edit.settings` (≤ 20 Hz while dragging, plus `commit` on release)
//  * physical edits → `edit.part` (separate message type and separate store slice)
//  * reconnect → `hello` → snapshot → re-send only the latest intent per control

import { ApiClient } from './rest';
import { WsClient, Throttle } from './ws';
import { liveTransport, mockSetting, probeBackend, type Transport } from './transport';
import type { Envelope, Part, RunAction, Settings, SliderKey, Units } from './types';
import type { AppStore } from '../store/store';
import type { PresetId } from '../store/presets';

interface PartIntent {
  patch: Record<string, unknown>;
  seq: number | null;
}

export class Session {
  readonly api: ApiClient;
  readonly ws: WsClient;
  readonly transport: Transport;
  private readonly store: AppStore;
  private clientSeq = 0;
  private settingsThrottle: Throttle<Settings>;
  private partThrottles = new Map<string, Throttle<Record<string, unknown>>>();
  private pendingSettings: { settings: Settings; seq: number | null } | null = null;
  private pendingParts = new Map<string, PartIntent>();
  private refetchTimer: ReturnType<typeof setTimeout> | null = null;
  private probeTimer: ReturnType<typeof setInterval> | null = null;
  private started = false;

  constructor(store: AppStore, transport: Transport) {
    this.store = store;
    this.transport = transport;
    this.api = new ApiClient(transport);
    this.settingsThrottle = new Throttle<Settings>((s, commit) => this.sendSettings(s, commit), 50);
    this.ws = new WsClient({
      transport,
      onEnvelope: (env) => this.onEnvelope(env),
      onState: (st, info) => store.getState().setWsState(st, info.attempt, info.nextDelayMs),
      onNewConnection: () => {
        this.clientSeq = 0;
        store.getState().newConnection();
      },
      getContext: () => {
        const c = store.getState().conn;
        return { epoch: c.epoch, revs: c.newest, appliedClientSeq: c.appliedClientSeq };
      },
      wantCandidates: () => store.getState().view.expert,
    });
  }

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    await this.refetchProject();
    this.ws.connect();
  }

  stop(): void {
    this.ws.close();
    this.settingsThrottle.cancel();
    for (const t of this.partThrottles.values()) t.cancel();
    if (this.refetchTimer) clearTimeout(this.refetchTimer);
    if (this.probeTimer) clearInterval(this.probeTimer);
  }

  /** In auto-mock mode keep looking for a real backend and tell the user when one answers. */
  watchForBackend(intervalMs = 10000): void {
    if (this.probeTimer) return;
    this.probeTimer = setInterval(async () => {
      const r = await probeBackend(1000);
      if (r.ok) {
        this.store.getState().setBackendDetected(true);
        if (this.probeTimer) clearInterval(this.probeTimer);
        this.probeTimer = null;
      }
    }, intervalMs);
  }

  // --------------------------------------------------------------------------------------------- inbound
  private onEnvelope(env: Envelope): void {
    const before = this.store.getState().conn.appliedClientSeq;
    const effects = this.store.getState().applyEnvelope(env);
    for (const e of effects) {
      if (e.type === 'project') this.store.getState().loadProject(e.project);
      else if (e.type === 'refetchProject') this.scheduleRefetch();
      else if (e.type === 'resendIntents') this.resendIntents();
      else if (e.type === 'announce') this.store.getState().announce(e.text);
    }
    const applied = this.store.getState().conn.appliedClientSeq;
    if (applied > before) this.onApplied(applied);
  }

  private onApplied(applied: number): void {
    if (this.pendingSettings && this.pendingSettings.seq !== null && this.pendingSettings.seq <= applied) this.pendingSettings = null;
    let partApplied = false;
    for (const [id, it] of this.pendingParts)
      if (it.seq !== null && it.seq <= applied) {
        this.pendingParts.delete(id);
        partApplied = true;
      }
    // the part record changed on the server (mass source, lock pose …): reload it
    if (partApplied) this.scheduleRefetch();
  }

  private resendIntents(): void {
    if (this.pendingSettings) this.sendSettings(this.pendingSettings.settings, true);
    for (const [id, it] of [...this.pendingParts]) {
      const seq = this.sendPart(id, it.patch);
      if (typeof it.patch.mass_kg === 'number') this.store.getState().setMassEdit(id, it.patch.mass_kg, seq, true);
    }
  }

  scheduleRefetch(delayMs = 120): void {
    if (this.refetchTimer) clearTimeout(this.refetchTimer);
    this.refetchTimer = setTimeout(() => {
      this.refetchTimer = null;
      void this.refetchProject();
    }, delayMs);
  }

  async refetchProject(): Promise<void> {
    try {
      const p = await this.api.project();
      this.store.getState().loadProject(p);
    } catch (e) {
      this.store.getState().setDatasetError(`Could not load the project: ${(e as Error).message}`);
    }
  }

  // --------------------------------------------------------------------------------------------- goals
  private nextSeq(): number {
    this.clientSeq += 1;
    return this.clientSeq;
  }

  private sendSettings(settings: Settings, commit: boolean): void {
    const seq = this.nextSeq();
    const ok = this.ws.send('edit.settings', { client_seq: seq, settings, commit });
    if (ok) {
      this.store.getState().markSent(seq);
      this.store.getState().setPendingSettingsSeq(seq);
      this.pendingSettings = { settings, seq };
    } else {
      this.clientSeq -= 1;
      this.pendingSettings = { settings, seq: null };
    }
  }

  /** Slider moved (pointermove / key): UI updates in the same frame; the edit is sent at ≤ 20 Hz. */
  setSlider(key: SliderKey, value: number, commit: boolean): void {
    const st = this.store.getState();
    st.setSlider(key, value);
    const s = this.store.getState().goals.settings;
    if (!s) return;
    if (commit) this.settingsThrottle.flush(s);
    else this.settingsThrottle.push(s);
  }

  commitSettings(): void {
    const s = this.store.getState().goals.settings;
    if (s) this.settingsThrottle.flush(s);
  }

  setPreset(p: PresetId): void {
    this.store.getState().setPreset(p);
    this.commitSettings();
  }

  setStage(stage: 1 | 2): void {
    this.store.getState().setStage(stage);
    this.commitSettings();
  }

  patchSettings(patch: Partial<Settings>): void {
    const s = this.store.getState().goals.settings;
    if (!s) return;
    this.store.getState().setGoalSettings({ ...s, ...patch });
    this.commitSettings();
  }

  // --------------------------------------------------------------------------------------------- physical
  private sendPart(id: string, patch: Record<string, unknown>): number | null {
    const seq = this.nextSeq();
    const ok = this.ws.send('edit.part', { client_seq: seq, part_id: id, patch });
    if (ok) {
      this.store.getState().markSent(seq);
      this.pendingParts.set(id, { patch: { ...(this.pendingParts.get(id)?.patch ?? {}), ...patch }, seq });
      return seq;
    }
    this.clientSeq -= 1;
    this.pendingParts.set(id, { patch: { ...(this.pendingParts.get(id)?.patch ?? {}), ...patch }, seq: null });
    return null;
  }

  private partThrottle(id: string): Throttle<Record<string, unknown>> {
    let t = this.partThrottles.get(id);
    if (!t) {
      t = new Throttle<Record<string, unknown>>((patch, commit) => {
        const seq = this.sendPart(id, patch);
        if (typeof patch.mass_kg === 'number') this.store.getState().setMassEdit(id, patch.mass_kg, seq, commit);
      }, 50);
      this.partThrottles.set(id, t);
    }
    return t;
  }

  /** Mass edit: the COM marker moves at once (local recompute); `edit.part` is sent at ≤ 20 Hz. */
  setMass(id: string, mass: number, commit: boolean): void {
    if (!(mass > 0) || !Number.isFinite(mass)) return;
    this.store.getState().setMassEdit(id, mass, this.store.getState().physical.massEdits[id]?.client_seq ?? null, false);
    const t = this.partThrottle(id);
    if (commit) t.flush({ mass_kg: mass });
    else t.push({ mass_kg: mass });
  }

  setLocked(id: string, locked: boolean): void {
    const seq = this.sendPart(id, { locked });
    this.store.getState().setLockEdit(id, locked, seq);
  }

  /** V2: mark a part optional (tag "optional"): the search may leave it out when it does not fit. */
  setOptional(id: string, optional: boolean): void {
    const part = this.store.getState().dataset.project?.parts.find((p) => p.id === id);
    const tags = (part?.tags ?? []).filter((t) => t !== 'optional');
    this.sendPart(id, { tags: optional ? [...tags, 'optional'] : tags });
  }

  // --------------------------------------------------------------------------------------------- run
  async run(action: RunAction): Promise<void> {
    if (!this.ws.send('run.control', { action })) {
      try {
        await this.api.run(action);
      } catch (e) {
        this.store.getState().announce(`Run control failed: ${(e as Error).message}`);
      }
    }
  }

  // --------------------------------------------------------------------------------------------- parts
  async addFiles(files: File[]): Promise<Part[]> {
    const stl = files.filter((f) => /\.stl$/i.test(f.name));
    const st = this.store.getState();
    if (!stl.length) {
      st.setDatasetError(files.length ? 'Only .stl files can be added.' : null);
      return [];
    }
    st.setUploading(+1);
    try {
      const parts = await this.api.addParts(stl);
      this.store.getState().upsertParts(parts);
      this.store.getState().announce(`Added ${parts.map((p) => p.name).join(', ')}`);
      if (parts[0]) this.store.getState().select(parts[0].id);
      this.scheduleRefetch();
      return parts;
    } catch (e) {
      this.store.getState().setDatasetError(`Adding parts failed: ${(e as Error).message}`);
      return [];
    } finally {
      this.store.getState().setUploading(-1);
    }
  }

  async confirmUnits(id: string, units: Units): Promise<Part | null> {
    try {
      const p = await this.api.confirmUnits(id, units);
      this.store.getState().upsertParts([p]);
      this.store.getState().dequeueUnits(id);
      this.store.getState().announce(`${p.name}: units ${units} confirmed — ${p.status}`);
      this.scheduleRefetch();
      return p;
    } catch (e) {
      this.store.getState().setDatasetError(`Confirming units failed: ${(e as Error).message}`);
      return null;
    }
  }

  async removePart(id: string): Promise<void> {
    try {
      const name = this.store.getState().dataset.parts[id]?.name ?? id;
      await this.api.deletePart(id);
      this.store.getState().removePartLocal(id);
      this.store.getState().clearMassEdit(id);
      this.store.getState().announce(`Removed ${name}`);
      this.scheduleRefetch();
    } catch (e) {
      this.store.getState().setDatasetError(`Removing the part failed: ${(e as Error).message}`);
    }
  }
}

// ----------------------------------------------------------------------------------------------- bootstrap
let current: Session | null = null;
export function session(): Session {
  if (!current) throw new Error('session not started');
  return current;
}
export function hasSession(): boolean {
  return current !== null;
}

export async function startSession(store: AppStore): Promise<Session> {
  const setting = mockSetting();
  let transport: Transport;
  let reason: string;
  let version: string | null = null;
  if (setting === 'force-live') {
    transport = liveTransport();
    reason = 'VITE_MOCK=0 (live backend)';
  } else {
    const probe = setting === 'auto' ? await probeBackend() : { ok: false };
    if (probe.ok) {
      transport = liveTransport();
      reason = 'backend answered /api/health';
      version = probe.version ?? null;
    } else {
      const { createMockTransport } = await import('../mock/mockBackend');
      transport = await createMockTransport();
      reason = setting === 'force-mock' ? 'VITE_MOCK=1' : 'no backend answered /api/health — using the in-browser mock';
      version = 'mock';
    }
  }
  store.getState().setMode(transport.mode, reason, version);
  const s = new Session(store, transport);
  current = s;
  if (transport.mode === 'mock' && setting === 'auto') s.watchForBackend();
  await s.start();
  return s;
}

/** For tests: install a session over a given transport. */
export function installSession(store: AppStore, transport: Transport): Session {
  const s = new Session(store, transport);
  current = s;
  store.getState().setMode(transport.mode, 'test', null);
  return s;
}
