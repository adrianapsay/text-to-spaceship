// In-browser MOCK backend implementing the REST + WebSocket interface of docs/api-contract.md.
// Used while the real backend is being written (VITE_MOCK=1, or automatically in dev when /api/health does not
// answer). Every screen shows a "MOCK DATA" banner in this mode. The mock never invents optimisation results:
//  * part properties come from fixtures computed from data/synthetic (scripts/build-mock-fixtures.mjs);
//  * layouts are AABB-stacked placeholders from a seeded layer packer, checked by an AABB-disjointness test;
//  * metrics are computed from those placeholders with the same aggregation code the UI uses;
//  * the selector rule and detail-ladder numbers are ILLUSTRATIVE and labelled MOCK;
//  * benchmarks, Size Study, Manufacturable Design, Stage 2 and CAD are NOT implemented (empty states).

import type {
  Envelope,
  Layout,
  Limits,
  Mat3,
  Part,
  ProjectSnapshot,
  Revs,
  RunAction,
  Settings,
  SliderKey,
  Vec3,
  FidelityResult,
} from '../api/types';
import { SOCKET_CLOSED, SOCKET_CONNECTING, SOCKET_OPEN, type SocketLike, type Transport } from '../api/transport';
import { encodeMesh } from '../api/rest';
import { normaliseRotations, eigSym3 } from '../lib/math3';
import { computeMetrics, normalisedWeights, type MetricsContext } from '../lib/physics';
import { activeGoalSliders } from '../store/presets';
import { aabbCheck, packOnce } from './packer';
import { MOCK_ALGOS, mockFidelity, mockIdeaMap, mockMap, mockProof, mockSelect, mockSweep, partStats } from './content';
import { canonicalise, checkMesh, massProps, parseStl, UNIT_SCALE, type ParsedMesh } from './stl';
import { bomCsv, mockBom } from '../lib/bom';

export interface MockFixtures {
  project: ProjectSnapshot;
  layouts: Layout[];
}

export interface MockOptions {
  meshLoader: (partId: string) => Promise<ArrayBuffer>;
  /** milliseconds between mock search attempts */
  searchIntervalMs?: number;
  /** delay before a socket opens / message delivery */
  latencyMs?: number;
  searchBudget?: number;
  fidelityStepMs?: number;
}

const DENSITY = 2700;

class MockSocket implements SocketLike {
  readyState = SOCKET_CONNECTING;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  seq = 0;
  applied = 0;
  wantCandidates = false;
  private readonly backend: MockBackend;
  constructor(backend: MockBackend) {
    this.backend = backend;
    setTimeout(() => {
      if (this.readyState !== SOCKET_CONNECTING) return;
      this.readyState = SOCKET_OPEN;
      backend.sockets.add(this);
      this.onopen?.({});
    }, backend.latency);
  }
  send(data: string): void {
    if (this.readyState !== SOCKET_OPEN) throw new Error('socket not open');
    let env: Envelope;
    try {
      env = JSON.parse(data) as Envelope;
    } catch {
      return;
    }
    setTimeout(() => this.backend.onClientMessage(this, env), this.backend.latency);
  }
  deliver(env: Envelope): void {
    if (this.readyState !== SOCKET_OPEN) return;
    const data = JSON.stringify(env);
    setTimeout(() => {
      if (this.readyState === SOCKET_OPEN) this.onmessage?.({ data });
    }, this.backend.latency);
  }
  close(code = 1000, reason = ''): void {
    if (this.readyState === SOCKET_CLOSED) return;
    this.readyState = SOCKET_CLOSED;
    this.backend.sockets.delete(this);
    setTimeout(() => this.onclose?.({ code, reason }), 0);
  }
}

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });
}
function file(body: string | ArrayBuffer, name: string, type: string): Response {
  return new Response(body, { status: 200, headers: { 'content-type': type, 'content-disposition': `attachment; filename="${name}"` } });
}
const notAvailable = (what: string) => json(404, { detail: `MOCK backend: ${what} is not available in mock mode (runs only in the real backend)` });
const notImplemented = (what: string) => json(501, { detail: `MOCK backend: ${what} is not implemented in mock mode` });

export class MockBackend {
  readonly sockets = new Set<MockSocket>();
  readonly latency: number;
  private project: ProjectSnapshot;
  private parts = new Map<string, Part>();
  private order: string[] = [];
  private rotations: Mat3[];
  private meshes = new Map<string, ArrayBuffer>();
  private raw = new Map<string, ParsedMesh>();
  private archive = new Map<string, Layout>();
  private bestId: string | null = null;
  /** last best before inputs changed; sent in snapshots (the client badges it "VALIDATED FOR PREVIOUS INPUTS") */
  private lastBestId: string | null = null;
  private candidate: Layout | null = null;
  private revs: Revs;
  private runStatus = 'IDLE';
  private runDetail = 'MOCK backend: no optimiser. "Optimise" runs a placeholder AABB layer packer.';
  private evaluations = 0;
  /** running time: milliseconds spent searching (pauses do not count), as the real backend reports it */
  private searchedMs = 0;
  private searchingSince: number | null = null;
  private searchTimer: ReturnType<typeof setInterval> | null = null;
  private attemptsLeft = 0;
  private layoutCounter = 1;
  private selector: { id: string; reasons: string[] };
  private fidelity = new Map<string, FidelityResult>();
  private readonly opts: Required<MockOptions>;
  private readonly fixtureLayouts: Layout[];

  constructor(fx: MockFixtures, opts: MockOptions) {
    this.opts = { searchIntervalMs: 450, latencyMs: 5, searchBudget: 40, fidelityStepMs: 700, ...opts };
    this.latency = this.opts.latencyMs;
    this.project = structuredClone(fx.project);
    this.rotations = normaliseRotations(this.project.rotations);
    for (const p of this.project.parts) {
      this.parts.set(p.id, p);
      this.order.push(p.id);
    }
    this.revs = { ...this.project.revs };
    this.fixtureLayouts = structuredClone(fx.layouts);
    for (const L of this.fixtureLayouts) this.admit(structuredClone(L));
    this.rescore();
    this.selector = mockSelect(this.project.settings, partStats(this.partList()));
    for (const p of this.partList()) if (p.status === 'VALID' || p.status === 'REPAIRED') this.fidelity.set(p.id, mockFidelity(p));
  }

  // ------------------------------------------------------------------------------------------- helpers
  private partList(): Part[] {
    return this.order.map((id) => this.parts.get(id)!).filter(Boolean);
  }
  private partsRecord(): Record<string, Part> {
    return Object.fromEntries(this.parts);
  }
  private packable(): Part[] {
    return this.partList().filter((p) => (p.status === 'VALID' || p.status === 'REPAIRED') && p.mass_kg != null);
  }
  private half(): Vec3 {
    const s = this.project.enclosure.size_mm ?? [100, 100, 340.5];
    return [s[0] / 2, s[1] / 2, s[2] / 2];
  }
  private ctx(): MetricsContext {
    const s = this.project.enclosure.size_mm ?? [100, 100, 340.5];
    return {
      rotations: this.rotations,
      limits: this.project.limits as Limits,
      enclosureZ: [-s[2] / 2, s[2] / 2],
      enclosureVolumeMm3: s[0] * s[1] * s[2],
      targetComMm: this.project.settings.target_com_mm,
      compactness: this.project.settings.compactness_definition,
    };
  }
  private isCurrent(L: Layout): boolean {
    return L.parts_rev >= this.revs.parts_rev && L.constraint_rev >= this.revs.constraint_rev;
  }
  private snapshot(): ProjectSnapshot {
    return { ...structuredClone(this.project), parts: structuredClone(this.partList()), revs: { ...this.revs }, mock: true };
  }
  private best(): Layout | null {
    return this.bestId ? this.archive.get(this.bestId) ?? null : null;
  }
  private now() {
    return new Date().toISOString();
  }

  private envelope(sock: MockSocket, type: string, payload: unknown): Envelope {
    sock.seq += 1;
    return {
      v: 1,
      type,
      seq: sock.seq,
      epoch: this.revs.epoch,
      parts_rev: this.revs.parts_rev,
      constraint_rev: this.revs.constraint_rev,
      mass_rev: this.revs.mass_rev,
      weights_rev: this.revs.weights_rev,
      applied_client_seq: sock.applied,
      ts: this.now(),
      payload,
    };
  }
  private sendTo(sock: MockSocket, type: string, payload: unknown) {
    sock.deliver(this.envelope(sock, type, payload));
  }
  private broadcast(type: string, payload: unknown, filter?: (s: MockSocket) => boolean) {
    for (const s of this.sockets) if (!filter || filter(s)) this.sendTo(s, type, payload);
  }

  /** Validate (AABB) + compute metrics, stamp current revs, add to the archive. */
  private admit(L: Layout): Layout | null {
    const parts = this.partsRecord();
    if (!L.poses.every((p) => parts[p.part_id])) return null;
    const check = aabbCheck(parts, L.poses, this.rotations, this.half());
    if (!check.ok) return null;
    const metrics = computeMetrics(parts, L.poses, this.ctx());
    const admitted: Layout = {
      ...L,
      status: L.status === 'FINAL' ? 'FINAL' : 'VALIDATED',
      stage: 1,
      parts_rev: this.revs.parts_rev,
      constraint_rev: this.revs.constraint_rev,
      mass_rev: this.revs.mass_rev,
      weights_rev: this.revs.weights_rev,
      metrics: { ...metrics, min_clearance_mm: Math.min(...check.separations.map((s) => s.gap_mm), ...check.containment.flatMap((c) => c.margin_mm)) },
      validation: { certified: true, validator_version: 'mock-aabb-1 (MOCK: AABB disjointness only)', tolerance_mm: 0, pairs: check.pairs, checked_at: this.now() },
      mock: true,
    };
    this.archive.set(admitted.id, admitted);
    return admitted;
  }

  /** Re-score current archive layouts under the current weights; return the best id (augmented Tchebycheff). */
  private rescore(): string | null {
    const s = this.project.settings;
    const cur = [...this.archive.values()].filter((L) => this.isCurrent(L) && L.stage === s.stage && L.metrics);
    if (!cur.length) {
      this.bestId = null;
      return null;
    }
    const f = cur.map((L) => ({
      L: L.metrics!.length_used_mm ?? 0,
      D: L.metrics!.com_error_mm ?? 0,
      T: L.metrics!.trace_kgm2 ?? 0,
      P: L.metrics!.products_norm_kgm2 ?? 0,
    }));
    const range = (k: 'L' | 'D' | 'T' | 'P', floor: number, utopiaZero: boolean) => {
      const vals = f.map((x) => x[k]);
      const lo = Math.min(...vals);
      const hi = Math.max(...vals);
      const u = utopiaZero ? 0 : lo - 0.01 * (hi - lo);
      return { u, d: Math.max(hi - u, floor) };
    };
    const uT = Math.min(...f.map((x) => x.T));
    const rL = range('L', 1, false);
    const rD = range('D', 0.5, true);
    const rT = range('T', 0.01 * uT, false);
    const rP = range('P', 0.01 * uT, true);
    const alpha = s.sliders.mass_symmetry / 100;
    const w = normalisedWeights(s.sliders, activeGoalSliders(s.stage));
    let bestG = Infinity;
    let bestId: string | null = null;
    cur.forEach((L, i) => {
      const nL = (f[i].L - rL.u) / rL.d;
      const nD = (f[i].D - rD.u) / rD.d;
      const nI = alpha * ((f[i].T - rT.u) / rT.d) + (1 - alpha) * ((f[i].P - rP.u) / rP.d);
      const terms = [(w.space ?? 0) * nL, (w.balance ?? 0) * nD, (w.inertia ?? 0) * nI];
      const g = Math.max(...terms) + 1e-3 * terms.reduce((a, b) => a + b, 0);
      L.scores = { normalised: { L: nL, D: nD, I: nI, G: null, H: null, C: null }, g, norm_epoch: 1 };
      L.weights_rev = this.revs.weights_rev;
      if (g < bestG - 1e-12) {
        bestG = g;
        bestId = L.id;
      }
    });
    this.bestId = bestId;
    return bestId;
  }

  private publishBestIfChanged(prev: string | null, source: 'archive' | 'search') {
    const b = this.best();
    if (b && b.id !== prev) this.broadcast('layout.validated', { layout: b, source });
  }

  private updateSelector() {
    const next = mockSelect(this.project.settings, partStats(this.partList()));
    if (next.id !== this.selector.id) {
      this.selector = next;
      this.broadcast('selector.changed', { algorithm: { id: next.id, label: MOCK_ALGOS[next.id] }, reasons: next.reasons });
    } else this.selector = next;
  }
  private selectorPayload() {
    return {
      algorithm: { id: this.selector.id, label: MOCK_ALGOS[this.selector.id] ?? this.selector.id },
      reasons: this.selector.reasons,
      evidence: [{ source: 'MOCK default rule', note: 'no benchmark evidence yet (illustrative rule, not the backend rule)' }],
      mock: true,
    };
  }

  private markAllStale(reason: string) {
    const b = this.best();
    if (b) {
      this.broadcast('layout.stale', { layout_id: b.id, reason });
      this.lastBestId = b.id;
    }
    this.bestId = null;
  }

  private setStatus(run_status: string, detail: string) {
    this.runStatus = run_status;
    this.runDetail = detail;
    this.broadcast('status', { run_status, detail });
  }

  // ------------------------------------------------------------------------------------------- edits
  private applySettings(settings: Settings) {
    const old = this.project.settings;
    const cableMode = (s: Settings) => (s.stage === 2 ? (s.sliders.cable >= 70 ? 'continuous' : s.sliders.cable > 0 ? 'soft' : 'default') : 'n/a');
    const constraintChange = old.stage !== settings.stage || cableMode(old) !== cableMode(settings);
    const weightsChange = JSON.stringify(old.sliders) !== JSON.stringify(settings.sliders) || JSON.stringify(old.target_com_mm) !== JSON.stringify(settings.target_com_mm);
    this.project.settings = structuredClone(settings);
    const prev = this.bestId;
    if (constraintChange) {
      this.revs.constraint_rev += 1;
      this.markAllStale(old.stage !== settings.stage ? `stage changed to ${settings.stage}` : 'cable-routing mode changed');
      if (settings.stage === 1) {
        // re-validate Stage 1 archive best-first under the new constraint_rev (the AABB check does not depend on it)
        for (const L of [...this.archive.values()]) if (L.parts_rev >= this.revs.parts_rev) this.admit({ ...L });
        this.rescore();
        this.publishBestIfChanged(null, 'archive');
      } else {
        this.setStatus('IDLE', 'MOCK backend has no Stage 2 engine: no ENGINEERING-CONSTRAINED layouts exist in mock mode.');
      }
    } else if (weightsChange) {
      this.revs.weights_rev += 1;
      this.rescore();
      this.publishBestIfChanged(prev, 'archive');
    }
    this.updateSelector();
  }

  private applyPartPatch(id: string, patch: Record<string, unknown>): Part | null {
    const p = this.parts.get(id);
    if (!p) return null;
    const next: Part = { ...p };
    let massChanged = false;
    if (typeof patch.mass_kg === 'number' && patch.mass_kg > 0 && p.mass_kg && p.inertia_com_kgm2) {
      const s = patch.mass_kg / p.mass_kg;
      next.mass_kg = patch.mass_kg;
      next.inertia_com_kgm2 = p.inertia_com_kgm2.map((r) => r.map((v) => v * s)) as Mat3;
      next.principal_kgm2 = p.principal_kgm2 ? (p.principal_kgm2.map((v) => v * s) as Vec3) : null;
      next.density_kg_m3 = p.volume_mm3 ? patch.mass_kg / (p.volume_mm3 * 1e-9) : p.density_kg_m3;
      next.mass_source = 'USER_MASS';
      massChanged = true;
    } else if (typeof patch.mass_kg === 'number' && patch.mass_kg > 0 && p.status === 'WITHHELD' && p.volume_mm3 == null) {
      next.mass_kg = patch.mass_kg;
      next.mass_source = 'USER_MASS';
      massChanged = true;
    }
    if (typeof patch.density_kg_m3 === 'number' && patch.density_kg_m3 > 0 && p.volume_mm3 && p.mass_kg && p.inertia_com_kgm2) {
      const m = patch.density_kg_m3 * p.volume_mm3 * 1e-9;
      const s = m / p.mass_kg;
      next.mass_kg = m;
      next.density_kg_m3 = patch.density_kg_m3;
      next.inertia_com_kgm2 = p.inertia_com_kgm2.map((r) => r.map((v) => v * s)) as Mat3;
      next.mass_source = 'USER_DENSITY';
      massChanged = true;
    }
    if (typeof patch.locked === 'boolean') {
      next.locked = patch.locked;
      const b = this.best();
      next.lock_pose = patch.locked ? b?.poses.find((q) => q.part_id === id) ?? null : null;
    }
    if (typeof patch.subsystem === 'string') next.subsystem = patch.subsystem;
    if (Array.isArray(patch.tags)) next.tags = patch.tags as string[];
    if (Array.isArray(patch.allowed_orients)) next.allowed_orients = patch.allowed_orients as number[];
    this.parts.set(id, next);
    if (massChanged) {
      this.revs.mass_rev += 1;
      const parts = this.partsRecord();
      for (const L of this.archive.values()) {
        if (!L.poses.every((q) => parts[q.part_id])) continue;
        L.metrics = { ...(L.metrics ?? {}), ...computeMetrics(parts, L.poses, this.ctx()), min_clearance_mm: L.metrics?.min_clearance_mm ?? null };
        L.mass_rev = this.revs.mass_rev;
      }
      const b = this.best();
      if (b) this.broadcast('metrics.update', { layout_id: b.id, metrics: b.metrics });
      const prev = this.bestId;
      this.rescore();
      this.publishBestIfChanged(prev, 'archive');
    }
    return next;
  }

  private async addFile(f: File, units: string | null): Promise<Part> {
    const buf = await f.arrayBuffer();
    const id = this.nextPartId();
    const name = f.name.replace(/\.stl$/i, '') || id;
    const sha = await sha256Hex(buf);
    const base: Part = {
      id, name, file: f.name, sha256: sha, units: 'mm', units_confirmed: false, status: 'NEEDS_UNITS',
      status_detail: 'confirm the file units', repairs: [], triangles: 0, display_triangles: 0, subsystem: 'unknown',
      labels: [], extents_mm: [0, 0, 0], volume_mm3: null, density_kg_m3: DENSITY, mass_kg: null, mass_source: 'WITHHELD',
      com_canonical_mm: null, inertia_com_kgm2: null, principal_kgm2: null, solidity: null, obb_fill: null,
      allowed_orients: this.rotations.map((_, i) => i), locked: false, lock_pose: null, tags: [],
    };
    let parsed: ParsedMesh;
    try {
      parsed = parseStl(buf);
    } catch (e) {
      const bad: Part = { ...base, status: 'WITHHELD', status_detail: (e as Error).message, units_confirmed: true };
      this.insertPart(bad);
      return bad;
    }
    this.raw.set(id, parsed);
    const c = canonicalise(parsed, 1);
    const part: Part = { ...base, triangles: parsed.indices.length / 3, display_triangles: parsed.indices.length / 3, extents_mm: c.extents };
    this.insertPart(part);
    if (units && UNIT_SCALE[units]) return this.confirmUnits(id, units)!;
    return part;
  }

  private nextPartId(): string {
    let n = this.order.length + 1;
    while (this.parts.has(`p${String(n).padStart(2, '0')}`)) n++;
    return `p${String(n).padStart(2, '0')}`;
  }
  private insertPart(p: Part) {
    this.parts.set(p.id, p);
    this.order.push(p.id);
    this.revs.parts_rev += 1;
    this.markAllStale(`parts changed: added ${p.name}`);
  }

  private confirmUnits(id: string, units: string): Part | null {
    const p = this.parts.get(id);
    const parsed = this.raw.get(id);
    if (!p || !parsed || !UNIT_SCALE[units]) return null;
    const c = canonicalise(parsed, UNIT_SCALE[units]);
    const chk = checkMesh(parsed);
    let indices = c.indices;
    let mp = massProps(c.positions64, indices);
    const repairs: string[] = [];
    if (mp.volume_mm3 < 0 && chk.boundaryEdges === 0) {
      indices = new Uint32Array(indices.length);
      for (let t = 0; t < c.indices.length; t += 3) {
        indices[t] = c.indices[t];
        indices[t + 1] = c.indices[t + 2];
        indices[t + 2] = c.indices[t + 1];
      }
      mp = massProps(c.positions64, indices);
      repairs.push('flipped winding (inverted normals)');
    }
    this.meshes.set(id, encodeMesh({ positions: c.positions, indices }));
    let next: Part;
    const aabb = c.extents[0] * c.extents[1] * c.extents[2];
    if (chk.boundaryEdges > 0 || chk.nonManifoldEdges > 0) {
      const detail = chk.boundaryEdges > 0 ? `open mesh — ${chk.boundaryLoops} hole${chk.boundaryLoops === 1 ? '' : 's'}` : `non-manifold mesh — ${chk.nonManifoldEdges} edges`;
      next = { ...p, units, units_confirmed: true, status: 'WITHHELD', status_detail: `${detail}; mass properties withheld (enter the mass yourself or remove the part)`, extents_mm: c.extents, mass_kg: null, mass_source: 'WITHHELD', volume_mm3: null };
    } else {
      const mass = DENSITY * mp.volume_mm3 * 1e-9;
      const I = mp.J_mm5.map((r) => r.map((v) => DENSITY * v * 1e-15)) as Mat3;
      const fill = aabb > 0 ? mp.volume_mm3 / aabb : 0;
      const minE = Math.min(...c.extents);
      const maxE = Math.max(...c.extents);
      const labels = [fill > 0.95 ? 'box-like' : null, minE < 0.1 * maxE ? 'plate-like' : null].filter(Boolean) as string[];
      next = {
        ...p, units, units_confirmed: true, status: repairs.length ? 'REPAIRED' : 'VALID', status_detail: repairs.length ? 'repaired' : 'closed mesh',
        repairs, extents_mm: c.extents, volume_mm3: mp.volume_mm3, density_kg_m3: DENSITY, mass_kg: mass, mass_source: 'ASSUMED',
        com_canonical_mm: mp.com_mm, inertia_com_kgm2: I, principal_kgm2: eigSym3(I).values,
        labels: labels.length ? labels : ['unclassified (MOCK)'],
      };
    }
    this.parts.set(id, next);
    this.revs.parts_rev += 1;
    this.markAllStale(`parts changed: ${next.name} units confirmed`);
    if (next.status === 'VALID' || next.status === 'REPAIRED') this.startFidelity(next);
    this.updateSelector();
    return next;
  }

  private startFidelity(p: Part) {
    const steps = 5;
    this.fidelity.set(p.id, { ...mockFidelity(p, 'PENDING', 0), levels: [] });
    this.broadcast('study.update', { study: 'fidelity', progress: 0, partial: { part_id: p.id, status: 'PENDING', progress: 0 } });
    for (let i = 1; i <= steps; i++) {
      setTimeout(() => {
        if (!this.parts.has(p.id)) return;
        const done = i === steps;
        const res = done ? mockFidelity(p) : mockFidelity(p, 'RUNNING', i * 2);
        this.fidelity.set(p.id, res);
        this.broadcast('study.update', {
          study: 'fidelity',
          progress: i / steps,
          partial: { part_id: p.id, status: res.status, progress: i / steps, level: res.levels[res.levels.length - 1]?.level ?? null },
        });
      }, i * this.opts.fidelityStepMs);
    }
  }

  // ------------------------------------------------------------------------------------------- run control
  private runControl(action: RunAction | string) {
    switch (action) {
      case 'start':
      case 'resume':
      case 'rerun':
        if (this.project.settings.stage === 2) {
          this.setStatus('IDLE', 'MOCK backend has no Stage 2 engine: nothing to search.');
          return;
        }
        if (action !== 'resume' || this.attemptsLeft <= 0) this.attemptsLeft = this.opts.searchBudget;
        this.stopClock();
        if (action !== 'resume') {
          this.evaluations = 0;
          this.searchedMs = 0;
        }
        this.searchingSince = Date.now();
        this.setStatus('SEARCHING', 'MOCK placeholder search (seeded AABB layer packer) — not an optimiser');
        this.startSearchTimer();
        break;
      case 'pause':
        this.stopSearchTimer();
        this.stopClock();
        this.setStatus('PAUSED', 'MOCK placeholder search paused');
        this.broadcast('progress', this.progressPayload());
        break;
      case 'reset':
        this.stopSearchTimer();
        this.stopClock();
        this.searchedMs = 0;
        this.archive.clear();
        this.revs.epoch += 1;
        for (const L of this.fixtureLayouts) this.admit(structuredClone(L));
        this.rescore();
        this.runStatus = 'IDLE';
        this.runDetail = 'MOCK archive reset to the fixture placeholder';
        for (const s of this.sockets) this.sendSnapshot(s);
        break;
    }
  }
  private startSearchTimer() {
    this.stopSearchTimer();
    this.searchTimer = setInterval(() => this.searchStep(), this.opts.searchIntervalMs);
  }
  private stopSearchTimer() {
    if (this.searchTimer) clearInterval(this.searchTimer);
    this.searchTimer = null;
  }
  private stopClock() {
    if (this.searchingSince != null) this.searchedMs += Date.now() - this.searchingSince;
    this.searchingSince = null;
  }
  private progressPayload() {
    const b = this.best();
    return {
      status: this.runStatus,
      evaluations: this.evaluations,
      best_g: b?.scores?.g ?? null,
      elapsed_s: (this.searchedMs + (this.searchingSince != null ? Date.now() - this.searchingSince : 0)) / 1000,
      recommended_min_s: null,
      recommended_note: 'MOCK backend: no recommended minimum run time (the real backend shows one where it was measured).',
      islands: [],
    };
  }
  private searchStep() {
    if (this.attemptsLeft <= 0) {
      // the placeholder packer has a fixed attempt budget; the real optimiser never stops on its own (only Pause)
      this.stopSearchTimer();
      this.stopClock();
      this.setStatus('PAUSED', `MOCK placeholder search paused after ${this.evaluations} attempts (the mock has a fixed attempt budget; the real optimiser searches until you press Pause) — not an optimiser, nothing is proven`);
      this.broadcast('progress', this.progressPayload());
      return;
    }
    this.attemptsLeft -= 1;
    this.evaluations += 1;
    const parts = this.packable();
    const s = this.project.enclosure.size_mm ?? [100, 100, 340.5];
    // a "step" = up to 400 seeded packer attempts; the first one that fits becomes the candidate
    let seed = 0;
    let res = packOnce(parts, this.rotations, { x: s[0], y: s[1], z: s[2] }, 1, {});
    for (let k = 0; k < 400; k++) {
      seed = 1000 + this.evaluations * 7919 + k * 104729 + this.revs.parts_rev * 31;
      res = packOnce(parts, this.rotations, { x: s[0], y: s[1], z: s[2] }, seed, { flip: this.evaluations % 3 === 0, centreXY: this.evaluations % 2 === 0 });
      if (res.fits) break;
    }
    const id = `L-MOCK-${String(++this.layoutCounter).padStart(4, '0')}`;
    const layout: Layout = {
      id, hash: `${seed.toString(16)}`, stage: 1, mode: 'default', status: 'CANDIDATE',
      parts_rev: this.revs.parts_rev, constraint_rev: this.revs.constraint_rev, mass_rev: this.revs.mass_rev, weights_rev: this.revs.weights_rev,
      poses: res.poses, extra_items: [], metrics: null, scores: null,
      algorithm: { id: 'mock_stack', label: 'MOCK placeholder stack', reason: 'MOCK placeholder (seeded AABB layer packer); not an optimisation result' },
      validation: null, origin: 'search', created: this.now(), mock: true,
    };
    if (res.fits) {
      this.candidate = layout;
      this.broadcast('layout.candidate', { layout }, (sk) => sk.wantCandidates);
      setTimeout(() => {
        const prev = this.bestId;
        const admitted = this.admit({ ...layout });
        if (this.candidate?.id === id) this.candidate = null;
        if (admitted) {
          this.rescore();
          this.publishBestIfChanged(prev, 'search');
          this.broadcast('pareto.update', { points: this.paretoPoints() });
        }
      }, Math.min(200, this.opts.searchIntervalMs / 2));
    }
    this.broadcast('progress', this.progressPayload());
  }

  private paretoPoints() {
    return [...this.archive.values()]
      .filter((L) => this.isCurrent(L) && L.metrics)
      .map((L) => ({ layout_id: L.id, L: L.metrics!.length_used_mm ?? 0, D: L.metrics!.com_error_mm ?? 0, I: L.metrics!.trace_kgm2 ?? 0, mock: true }));
  }

  // ------------------------------------------------------------------------------------------- WebSocket
  private sendSnapshot(sock: MockSocket) {
    this.sendTo(sock, 'state.snapshot', {
      project: this.snapshot(),
      best_validated: this.best() ?? (this.lastBestId ? this.archive.get(this.lastBestId) ?? null : null),
      candidate: sock.wantCandidates ? this.candidate : null,
      run_status: this.runStatus,
      selector: this.selectorPayload(),
      progress: this.searchedMs || this.searchingSince != null ? this.progressPayload() : null,
    });
    this.sendTo(sock, 'status', { run_status: this.runStatus, detail: this.runDetail });
  }

  onClientMessage(sock: MockSocket, env: Envelope) {
    const p = (env.payload ?? {}) as Record<string, unknown>;
    switch (env.type) {
      case 'hello':
        sock.wantCandidates = !!p.want_candidates;
        this.sendSnapshot(sock);
        break;
      case 'edit.settings': {
        const cs = Number(p.client_seq) || 0;
        if (p.settings) this.applySettings(p.settings as Settings);
        sock.applied = Math.max(sock.applied, cs);
        this.sendTo(sock, 'edit.ack', { client_seq: cs });
        break;
      }
      case 'edit.part': {
        const cs = Number(p.client_seq) || 0;
        this.applyPartPatch(String(p.part_id), (p.patch ?? {}) as Record<string, unknown>);
        sock.applied = Math.max(sock.applied, cs);
        this.sendTo(sock, 'edit.ack', { client_seq: cs });
        break;
      }
      case 'run.control':
        this.runControl(String(p.action));
        break;
      case 'ping':
        this.sendTo(sock, 'pong', {});
        break;
    }
  }

  /** Test hook: drop every connection (clients reconnect with backoff). */
  dropConnections() {
    for (const s of [...this.sockets]) s.close(1006, 'MOCK connection drop');
  }

  // ------------------------------------------------------------------------------------------- REST
  async handle(path: string, init: RequestInit = {}): Promise<Response> {
    const url = new URL(path, 'http://mock.local');
    const method = (init.method ?? 'GET').toUpperCase();
    const seg = url.pathname.replace(/^\/api\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
    const body = async (): Promise<Record<string, unknown>> => {
      if (typeof init.body === 'string') return JSON.parse(init.body) as Record<string, unknown>;
      return {};
    };
    await new Promise((r) => setTimeout(r, this.latency));
    try {
      const [a, b, c, d] = seg;
      if (a === 'health') return json(200, { ok: true, version: 'mock' });
      if (a === 'project' && method === 'GET') return json(200, this.snapshot());
      if (a === 'settings' && method === 'PUT') {
        this.applySettings((await body()) as unknown as Settings);
        return json(200, this.project.settings);
      }
      if (a === 'run' && method === 'POST') {
        this.runControl(String((await body()).action));
        return json(200, { run_status: this.runStatus });
      }
      if (a === 'parts') {
        if (!b && method === 'POST') {
          const fd = init.body as FormData;
          const files = fd && typeof fd.getAll === 'function' ? (fd.getAll('files[]') as File[]) : [];
          const units = fd && typeof fd.get === 'function' ? (fd.get('units') as string | null) : null;
          if (!files.length) return json(400, { detail: 'no files' });
          const out: Part[] = [];
          for (const f of files) out.push(await this.addFile(f, units));
          this.updateSelector();
          return json(200, out);
        }
        if (b && c === 'units' && method === 'POST') {
          const res = this.confirmUnits(b, String((await body()).units));
          return res ? json(200, res) : json(400, { detail: 'unknown part or units' });
        }
        if (b && c === 'mesh') {
          if (this.meshes.has(b)) return new Response(this.meshes.get(b)!.slice(0), { headers: { 'content-type': 'application/octet-stream' } });
          const p = this.parts.get(b);
          if (!p || p.status === 'NEEDS_UNITS') return json(404, { detail: 'no mesh' });
          const buf = await this.opts.meshLoader(b);
          this.meshes.set(b, buf);
          return new Response(buf.slice(0), { headers: { 'content-type': 'application/octet-stream' } });
        }
        if (b && c === 'fidelity') {
          const f = this.fidelity.get(b);
          if (!this.parts.has(b)) return json(404, { detail: 'unknown part' });
          return json(200, f ?? { status: 'PENDING', levels: [], chosen: {}, reasons: {}, stop_reason: null, mock: true, mock_note: 'MOCK: not started' });
        }
        if (b && c === 'proxy') return notAvailable('proxy geometry');
        if (b && !c && method === 'PATCH') {
          const res = this.applyPartPatch(b, await body());
          return res ? json(200, res) : json(404, { detail: 'unknown part' });
        }
        if (b && !c && method === 'DELETE') {
          if (!this.parts.has(b)) return json(404, { detail: 'unknown part' });
          const name = this.parts.get(b)!.name;
          this.parts.delete(b);
          this.order = this.order.filter((x) => x !== b);
          this.fidelity.delete(b);
          this.revs.parts_rev += 1;
          this.markAllStale(`parts changed: removed ${name}`);
          this.updateSelector();
          return new Response(null, { status: 204 });
        }
      }
      if (a === 'layouts') {
        if (!b && method === 'GET') {
          const status = url.searchParams.get('status');
          const limit = Number(url.searchParams.get('limit') || 200);
          const list = [...this.archive.values()]
            .filter((L) => !status || L.status === status)
            .sort((x, y) => (x.created < y.created ? 1 : -1))
            .slice(0, limit)
            .map((L) => ({ ...L, poses: undefined, part_ids: L.poses.map((q) => q.part_id) }));
          return json(200, list);
        }
        const L = b ? this.archive.get(b) : undefined;
        if (!L) return json(404, { detail: 'unknown layout' });
        if (!c && method === 'GET') return json(200, L);
        // M4: combined per wall and one piece run only in the real backend (FEA, optimiser)
        if (c === 'bracket-layouts') return notAvailable('bracket layouts (combined per wall, one piece)');
        if (c === 'bom' && method === 'GET') {
          // V2 WS6: the bill of materials, built in the browser from the placeholder layout (tagged mock)
          const bom = mockBom(L, this.snapshot());
          if (url.searchParams.get('format') === 'csv') return file(bomCsv(bom), `bom_${L.id}_MOCK.csv`, 'text/csv');
          return json(200, bom);
        }
        if (c === 'final' && method === 'POST') {
          if (!this.isCurrent(L)) return json(409, { detail: 'layout is validated for previous inputs; re-run first' });
          const re = this.admit({ ...L, status: 'FINAL' });
          if (!re) return json(409, { detail: 'MOCK re-validation failed' });
          if (this.bestId === re.id) this.broadcast('layout.validated', { layout: re, source: 'archive' });
          return json(200, re);
        }
        if (c === 'proof') {
          const check = aabbCheck(this.partsRecord(), L.poses, this.rotations, this.half());
          const proof = mockProof(L, this.partsRecord(), check, this.half(), (L.metrics?.com_mm as Vec3) ?? null);
          if (!d) return json(200, proof);
          if (d === 'download') {
            const kind = url.searchParams.get('kind');
            if (kind === 'md') return file(proof.markdown, `proof_${L.id}.md`, 'text/markdown');
            if (kind === 'json') return file(JSON.stringify(proof.certificate, null, 1), `certificate_${L.id}.json`, 'application/json');
            return notImplemented('the stand-alone checker script');
          }
        }
      }
      if (a === 'selector') {
        const stats = partStats(this.partList());
        if (!b) return json(200, this.selectorPayload());
        if (b === 'sweep') return json(200, mockSweep(this.project.settings, stats, (url.searchParams.get('slider') ?? 'space') as SliderKey));
        if (b === 'map') {
          const n = Math.max(3, Math.min(101, Number(url.searchParams.get('n') || 41)));
          return json(200, mockMap(this.project.settings, stats, (url.searchParams.get('x') ?? 'space') as SliderKey, (url.searchParams.get('y') ?? 'balance') as SliderKey, n));
        }
      }
      if (a === 'ideamap') return json(200, mockIdeaMap(this.partList(), this.project.settings, this.best(), this.selector));
      if (a === 'pareto') return json(200, { points: this.paretoPoints(), hv: null, norm_epoch: 1, mock: true });
      if (a === 'benchmarks') return method === 'POST' ? notImplemented('benchmark runs') : notAvailable('benchmark results');
      if (a === 'studies' && b === 'size') return c === 'run' ? notImplemented('the Size Study') : notAvailable('Size Study results');
      if (a === 'mfg') return b === 'run' ? notImplemented('Manufacturable Design') : notAvailable('Manufacturable Design results');
      if (a === 'items') return notAvailable('extra-item meshes');
      if (a === 'saved-stl') return notAvailable('saved STL files');
      if (a === 'design-options') return notAvailable('bracket design settings');
      if (a === 'fidelity') {
        if (b === 'run' && method === 'POST') {
          const ids = ((await body()).part_ids as string[] | undefined) ?? this.packable().map((p) => p.id);
          for (const id of ids) {
            const p = this.parts.get(id);
            if (p && (p.status === 'VALID' || p.status === 'REPAIRED')) this.startFidelity(p);
          }
          return json(200, { started: ids, mock: true });
        }
        if (b === 'summary')
          return json(200, {
            parts: this.partList()
              .filter((p) => this.fidelity.has(p.id))
              .map((p) => ({ part_id: p.id, name: p.name, chosen: this.fidelity.get(p.id)!.chosen })),
            mock: true,
          });
      }
      if (a === 'cad') {
        if (b === 'status') return json(200, { status: 'NOT_CONFIGURED', detail: 'Fusion 360 integration is not configured (MOCK backend).' });
        if (b === 'package') return notImplemented('the Fusion export package');
      }
      if (a === 'export' && b) {
        const L = this.archive.get(b);
        if (!L) return json(404, { detail: 'unknown layout' });
        const kind = url.searchParams.get('kind');
        if (kind === 'json') return file(JSON.stringify({ mock: true, layout: L }, null, 1), `layout_${L.id}_MOCK.json`, 'application/json');
        if (kind === 'csv') {
          const rows = ['part_id,name,orient,x_mm,y_mm,z_mm'];
          for (const q of L.poses) rows.push([q.part_id, this.parts.get(q.part_id)?.name ?? '', q.orient, ...q.t_um.map((v) => (v / 1000).toFixed(3))].join(','));
          return file(`# MOCK placeholder layout ${L.id}\n${rows.join('\n')}\n`, `layout_${L.id}_MOCK.csv`, 'text/csv');
        }
        return notImplemented(`export kind ${kind}`);
      }
      return json(404, { detail: `MOCK backend: no route ${method} ${url.pathname}` });
    } catch (e) {
      return json(500, { detail: `MOCK backend error: ${(e as Error).message}` });
    }
  }

  transport(): Transport & { backend: MockBackend } {
    return {
      mode: 'mock',
      fetch: (path, init) => this.handle(path, init),
      openSocket: () => new MockSocket(this),
      backend: this,
    };
  }
}

async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  try {
    const d = await crypto.subtle.digest('SHA-256', buf);
    return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('');
  } catch {
    return `nohash-${buf.byteLength}`;
  }
}

/** Load the fixtures written by scripts/build-mock-fixtures.mjs from the static `mock-fixtures/` folder. */
export async function createMockTransport(base: string = import.meta.env.BASE_URL ?? '/'): Promise<Transport & { backend: MockBackend }> {
  const root = `${base.replace(/\/?$/, '/')}mock-fixtures/`;
  const [project, layouts] = await Promise.all([
    window.fetch(`${root}project.json`).then((r) => {
      if (!r.ok) throw new Error(`mock fixtures missing (${r.status}); run "npm run fixtures"`);
      return r.json() as Promise<ProjectSnapshot>;
    }),
    window.fetch(`${root}layouts.json`).then((r) => r.json() as Promise<{ layouts: Layout[] }>),
  ]);
  const backend = new MockBackend(
    { project, layouts: layouts.layouts },
    {
      meshLoader: async (id) => {
        const r = await window.fetch(`${root}meshes/${id}.bin`);
        if (!r.ok) throw new Error(`mock mesh ${id} missing`);
        return r.arrayBuffer();
      },
    },
  );
  return backend.transport();
}
