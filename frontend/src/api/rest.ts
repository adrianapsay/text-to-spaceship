// Typed REST client for docs/api-contract.md §3.
import type { Transport } from './transport';
import type { BuilderMeta, BuilderResponse, BuilderView, DesignSummary, QuestionView } from '../builder/types';
import type { Analysis, CadEntry, CadList, CatalogList, ProjectInfo, SendResult } from '../builder/analysisTypes';
import type {
  Attribution,
  Benchmarks,
  BracketLayoutMode,
  BracketLayouts,
  BracketOverride,
  CadStatus,
  ContestResults,
  DesignOptions,
  FeaView,
  LargestSize,
  FidelityResult,
  FidelitySummary,
  FreeRotationResult,
  IdeaMap,
  Layout,
  LayoutRunSettings,
  LayoutSummary,
  MfgResult,
  OnePieceEstimate,
  Pareto,
  Part,
  ProjectSnapshot,
  Proof,
  RunAction,
  SavedStl,
  SelectorChoice,
  SelectorMap,
  SelectorSweep,
  Settings,
  SizeStudy,
  Units,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  constructor(status: number, path: string, message: string) {
    super(message);
    this.status = status;
    this.path = path;
  }
  /** 404 / 405 / 501: the backend does not provide this yet → show an empty state, not an error. */
  get notAvailable(): boolean {
    return this.status === 404 || this.status === 405 || this.status === 501;
  }
}

export interface MeshData {
  positions: Float32Array;
  indices: Uint32Array;
}

/** Decode the contract's binary mesh: uint32 nv, uint32 nt, float32[3nv], uint32[3nt], little-endian. */
export function decodeMesh(buf: ArrayBuffer): MeshData {
  if (buf.byteLength < 8) throw new Error('mesh too short');
  const dv = new DataView(buf);
  const nv = dv.getUint32(0, true);
  const nt = dv.getUint32(4, true);
  const need = 8 + nv * 12 + nt * 12;
  if (buf.byteLength < need) throw new Error(`mesh truncated: ${buf.byteLength} < ${need} bytes`);
  const positions = new Float32Array(nv * 3);
  const indices = new Uint32Array(nt * 3);
  for (let i = 0; i < nv * 3; i++) positions[i] = dv.getFloat32(8 + i * 4, true);
  const off = 8 + nv * 12;
  for (let i = 0; i < nt * 3; i++) {
    const v = dv.getUint32(off + i * 4, true);
    if (v >= nv) throw new Error(`mesh index ${v} out of range (nv = ${nv})`);
    indices[i] = v;
  }
  return { positions, indices };
}

export function encodeMesh(m: MeshData): ArrayBuffer {
  const nv = m.positions.length / 3;
  const nt = m.indices.length / 3;
  const buf = new ArrayBuffer(8 + nv * 12 + nt * 12);
  const dv = new DataView(buf);
  dv.setUint32(0, nv, true);
  dv.setUint32(4, nt, true);
  for (let i = 0; i < nv * 3; i++) dv.setFloat32(8 + i * 4, m.positions[i], true);
  const off = 8 + nv * 12;
  for (let i = 0; i < nt * 3; i++) dv.setUint32(off + i * 4, m.indices[i], true);
  return buf;
}

export type ExportKind = 'report_md' | 'report_html' | 'csv' | 'json' | 'stl_zip';
export type ProofKind = 'md' | 'json' | 'checker';

export class ApiClient {
  readonly t: Transport;
  constructor(t: Transport) {
    this.t = t;
  }

  private async req(path: string, init?: RequestInit): Promise<Response> {
    let r: Response;
    try {
      r = await this.t.fetch(path, init);
    } catch (e) {
      throw new ApiError(0, path, `network error: ${(e as Error).message}`);
    }
    if (!r.ok) {
      let msg = `${r.status} ${r.statusText}`;
      try {
        const j = (await r.clone().json()) as { detail?: unknown; message?: string };
        if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
        else if (j?.message) msg = j.message;
      } catch {
        /* not JSON */
      }
      throw new ApiError(r.status, path, msg);
    }
    return r;
  }
  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    const r = await this.req(path, init);
    return (await r.json()) as T;
  }
  private send<T>(method: string, path: string, body?: unknown): Promise<T> {
    return this.json<T>(path, {
      method,
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  // ------------------------------------------------------------------------------------- V3 CubeSat Builder
  builderMeta() {
    return this.json<BuilderMeta>('/api/builder/meta');
  }
  builderDesigns() {
    return this.json<{ designs: DesignSummary[] }>('/api/builder/designs');
  }
  builderCreate(req: { name?: string; statement?: string }, expert = false) {
    return this.send<BuilderResponse>('POST', `/api/builder/designs${expert ? '?expert=1' : ''}`, req);
  }
  builderGet(id: string, expert = false) {
    return this.json<BuilderResponse>(`/api/builder/designs/${encodeURIComponent(id)}${expert ? '?expert=1' : ''}`);
  }
  builderRename(id: string, name: string) {
    return this.send<BuilderResponse>('PATCH', `/api/builder/designs/${encodeURIComponent(id)}`, { name });
  }
  builderStatement(id: string, text: string, expert = false) {
    return this.send<BuilderResponse>('POST', `/api/builder/designs/${encodeURIComponent(id)}/statement${expert ? '?expert=1' : ''}`, { text });
  }
  builderAnswer(id: string, qid: string, answer: { value?: unknown; unknown?: boolean }, expert = false) {
    return this.send<BuilderResponse>('POST', `/api/builder/designs/${encodeURIComponent(id)}/answer${expert ? '?expert=1' : ''}`, { qid, ...answer });
  }
  builderUnanswer(id: string, qid: string, expert = false) {
    return this.send<BuilderResponse>('DELETE', `/api/builder/designs/${encodeURIComponent(id)}/answer/${encodeURIComponent(qid)}${expert ? '?expert=1' : ''}`);
  }
  builderDefaults(id: string, expert = false) {
    return this.send<BuilderResponse>('POST', `/api/builder/designs/${encodeURIComponent(id)}/defaults${expert ? '?expert=1' : ''}`);
  }
  builderQuestions(id: string, expert = false) {
    return this.json<{ questions: QuestionView[]; view: BuilderView }>(`/api/builder/designs/${encodeURIComponent(id)}/questions${expert ? '?expert=1' : ''}`);
  }
  builderAnalysis(id: string) {
    return this.json<Analysis>(`/api/builder/designs/${encodeURIComponent(id)}/analysis`);
  }
  builderSelect(id: string, slot: string, component: string | null, qty = 1, expert = false) {
    return this.send<BuilderResponse>('POST', `/api/builder/designs/${encodeURIComponent(id)}/selection${expert ? '?expert=1' : ''}`, { slot, component, qty });
  }
  builderUnselect(id: string, slot: string, expert = false) {
    return this.send<BuilderResponse>('DELETE', `/api/builder/designs/${encodeURIComponent(id)}/selection/${encodeURIComponent(slot)}${expert ? '?expert=1' : ''}`);
  }
  builderPrefs(id: string, prefs: Record<string, number | null>, expert = false) {
    return this.send<BuilderResponse>('PATCH', `/api/builder/designs/${encodeURIComponent(id)}/prefs${expert ? '?expert=1' : ''}`, prefs);
  }
  builderSend(id: string, switchTo = true) {
    return this.send<SendResult>('POST', `/api/builder/designs/${encodeURIComponent(id)}/send`, { switch: switchTo });
  }
  projects() {
    return this.json<{ projects: ProjectInfo[]; current: string }>('/api/projects');
  }
  projectSwitch(name: string) {
    return this.send<{ project: string; switched: boolean; previous?: string }>('POST', '/api/projects/switch', { name });
  }
  builderCad() {
    return this.json<CadList>('/api/builder/cad');
  }
  builderCadImport(cid: string, file: File, origin: 'manufacturer' | 'reconstructed' = 'manufacturer') {
    const fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('origin', origin);
    return this.json<CadEntry>(`/api/builder/cad/${encodeURIComponent(cid)}/import`, { method: 'POST', body: fd });
  }
  builderCadSimplified(cid: string) {
    return this.send<CadEntry>('POST', `/api/builder/cad/${encodeURIComponent(cid)}/simplified`);
  }
  builderCadDelete(cid: string) {
    return this.send<{ ok: boolean }>('DELETE', `/api/builder/cad/${encodeURIComponent(cid)}`);
  }
  builderCatalog(category?: string) {
    return this.json<CatalogList>(`/api/builder/catalog${category ? `?category=${encodeURIComponent(category)}` : ''}`);
  }

  health() {
    return this.json<{ ok: boolean; version: string }>('/api/health');
  }
  project() {
    return this.json<ProjectSnapshot>('/api/project');
  }
  async addParts(files: File[], units?: Units): Promise<Part[]> {
    const fd = new FormData();
    for (const f of files) fd.append('files[]', f, f.name);
    if (units) fd.append('units', units);
    const r = await this.json<Part[] | { parts: Part[] }>('/api/parts', { method: 'POST', body: fd });
    return Array.isArray(r) ? r : r.parts;
  }
  confirmUnits(id: string, units: Units) {
    return this.send<Part>('POST', `/api/parts/${encodeURIComponent(id)}/units`, { units });
  }
  patchPart(id: string, patch: Partial<Pick<Part, 'mass_kg' | 'density_kg_m3' | 'locked' | 'allowed_orients' | 'tags' | 'subsystem'>>) {
    return this.send<Part>('PATCH', `/api/parts/${encodeURIComponent(id)}`, patch);
  }
  async deletePart(id: string): Promise<void> {
    await this.req(`/api/parts/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }
  async mesh(id: string, lod: 'display' | 'full' = 'display'): Promise<MeshData> {
    const r = await this.req(`/api/parts/${encodeURIComponent(id)}/mesh?lod=${lod}`);
    return decodeMesh(await r.arrayBuffer());
  }
  async itemMesh(url: string): Promise<MeshData> {
    const r = await this.req(url);
    return decodeMesh(await r.arrayBuffer());
  }
  /** V2: what a designed bracket's FEA colour maps show (fields, units, maxima) */
  itemFea(itemId: string) {
    return this.json<FeaView>(`/api/items/${encodeURIComponent(itemId)}/fea`);
  }
  /** V2: one colour-map field: one value per vertex of the bracket's mesh */
  async itemFeaField(itemId: string, field: string): Promise<Float32Array> {
    const r = await this.req(`/api/items/${encodeURIComponent(itemId)}/fea/${encodeURIComponent(field)}`);
    return new Float32Array(await r.arrayBuffer());
  }
  putSettings(s: Settings) {
    return this.send<Settings>('PUT', '/api/settings', s);
  }
  run(action: RunAction) {
    return this.send<unknown>('POST', '/api/run', { action });
  }
  async layouts(q: { status?: string; limit?: number } = {}): Promise<LayoutSummary[]> {
    const qs = new URLSearchParams();
    if (q.status) qs.set('status', q.status);
    if (q.limit) qs.set('limit', String(q.limit));
    const r = await this.json<LayoutSummary[] | { layouts: LayoutSummary[] }>(`/api/layouts${qs.size ? `?${qs}` : ''}`);
    return Array.isArray(r) ? r : r.layouts;
  }
  layout(id: string) {
    return this.json<Layout>(`/api/layouts/${encodeURIComponent(id)}`);
  }
  finalize(id: string) {
    return this.send<Layout>('POST', `/api/layouts/${encodeURIComponent(id)}/final`);
  }
  proof(id: string) {
    return this.json<Proof>(`/api/layouts/${encodeURIComponent(id)}/proof`);
  }
  proofDownloadPath(id: string, kind: ProofKind) {
    return `/api/layouts/${encodeURIComponent(id)}/proof/download?kind=${kind}`;
  }
  selector() {
    return this.json<SelectorChoice>('/api/selector');
  }
  selectorSweep(slider: string) {
    return this.json<SelectorSweep>(`/api/selector/sweep?slider=${encodeURIComponent(slider)}`);
  }
  selectorMap(x: string, y: string, n = 41) {
    return this.json<SelectorMap | string[][]>(`/api/selector/map?x=${encodeURIComponent(x)}&y=${encodeURIComponent(y)}&n=${n}`);
  }
  ideamap() {
    return this.json<IdeaMap>('/api/ideamap');
  }
  pareto() {
    return this.json<Pareto>('/api/pareto');
  }
  benchmarks(block?: string) {
    if (!block) return this.json<Benchmarks>('/api/benchmarks');
    const [instance, preset] = block.split('|');
    return this.json<Benchmarks>(`/api/benchmarks?instance=${encodeURIComponent(instance)}&preset=${encodeURIComponent(preset ?? '')}`);
  }
  runBenchmarks() {
    return this.send<unknown>('POST', '/api/benchmarks/run', {});
  }
  sizeStudy() {
    return this.json<SizeStudy>('/api/studies/size');
  }
  runSizeStudy(body: Record<string, unknown> = {}) {
    return this.send<unknown>('POST', '/api/studies/size/run', body);
  }
  freeRotation() {
    return this.json<FreeRotationResult>('/api/experiments/free-rotation');
  }
  runFreeRotation(body: Record<string, unknown> = {}) {
    return this.send<unknown>('POST', '/api/experiments/free-rotation/run', body);
  }
  mfg() {
    return this.json<MfgResult>('/api/mfg');
  }
  runMfg(body: Record<string, unknown> = {}) {
    return this.send<unknown>('POST', '/api/mfg/run', body);
  }
  fidelity(partId: string) {
    return this.json<FidelityResult>(`/api/parts/${encodeURIComponent(partId)}/fidelity`);
  }
  runFidelity(body: { part_ids?: string[]; budget_s?: number } = {}) {
    return this.send<unknown>('POST', '/api/fidelity/run', body);
  }
  fidelitySummary() {
    return this.json<FidelitySummary>('/api/fidelity/summary');
  }
  attribution() {
    return this.json<Attribution>('/api/stage2/attribution');
  }
  runAttribution() {
    return this.send<unknown>('POST', '/api/stage2/attribution/run', {});
  }
  gdContest() {
    return this.json<ContestResults>('/api/gd/contest');
  }
  largestSize() {
    return this.json<LargestSize>('/api/studies/largest-size');
  }
  runLargestSize() {
    return this.send<unknown>('POST', '/api/studies/largest-size/run', {});
  }
  /** design the layout's brackets; `pids` redesigns only those, `overrides` sets their material / thickness (WS4) */
  designBrackets(layoutId: string, req: { pids?: string[]; overrides?: Record<string, BracketOverride> } = {}) {
    return this.send<unknown>('POST', `/api/layouts/${encodeURIComponent(layoutId)}/design-brackets`, req);
  }
  /** V2: launch environments, materials and the ranges of the per-bracket settings */
  designOptions() {
    return this.json<DesignOptions>('/api/design-options');
  }
  /** M4: the layout's three bracket layouts side by side (one per part, combined per wall, one piece) */
  bracketLayouts(layoutId: string) {
    return this.json<BracketLayouts>(`/api/layouts/${encodeURIComponent(layoutId)}/bracket-layouts`);
  }
  /** M4: the one piece's predicted size, time and memory before it is started */
  onePieceEstimate(layoutId: string, settings: LayoutRunSettings = {}) {
    return this.send<OnePieceEstimate>('POST', `/api/layouts/${encodeURIComponent(layoutId)}/bracket-layouts/one_piece/estimate`, { settings });
  }
  /** M4: design the combined brackets or the one piece in the background */
  runBracketLayout(layoutId: string, mode: 'combined' | 'one_piece', req: { settings?: LayoutRunSettings; overrides?: Record<string, LayoutRunSettings> } = {}) {
    return this.send<{ status: string; layout_id: string; mode: string }>('POST', `/api/layouts/${encodeURIComponent(layoutId)}/bracket-layouts/${mode}/run`, req);
  }
  /** V2: the whole-satellite check (frame held at the rail ends) of one bracket layout, in the background */
  frameCheck(layoutId: string, mode: BracketLayoutMode) {
    return this.send<{ status: string; layout_id: string; mode: string }>('POST', `/api/layouts/${encodeURIComponent(layoutId)}/bracket-layouts/${mode}/frame-check`, {});
  }
  /** M4: "Use for saved STL files": the bracket layout the layout is shown and saved with */
  useBracketLayout(layoutId: string, mode: BracketLayoutMode) {
    return this.send<{ layout_id: string; chosen: BracketLayoutMode; status: string }>('POST', `/api/layouts/${encodeURIComponent(layoutId)}/bracket-layouts/use`, { mode });
  }
  /** V2: the saved STL files of the designed best layout */
  savedStl() {
    return this.json<SavedStl>('/api/saved-stl');
  }
  saveStl(layoutId: string) {
    return this.send<{ status: string; layout_id: string; folder: string }>('POST', '/api/saved-stl', { layout_id: layoutId });
  }
  savedStlZipPath() {
    return '/api/saved-stl/download';
  }
  cadStatus() {
    return this.json<CadStatus>('/api/cad/status');
  }
  cadPackage(layoutId: string) {
    return this.send<{ path?: string; download?: string; [k: string]: unknown }>('POST', `/api/cad/package/${encodeURIComponent(layoutId)}`);
  }
  exportPath(layoutId: string, kind: ExportKind) {
    return `/api/export/${encodeURIComponent(layoutId)}?kind=${kind}`;
  }

  /** Download any API path as a file (works for both live and mock transports). */
  async download(path: string, filename: string): Promise<void> {
    const r = await this.req(path);
    const blob = await r.blob();
    const cd = r.headers.get('content-disposition') ?? '';
    const m = /filename="?([^";]+)"?/i.exec(cd);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = m?.[1] ?? filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}

/** Run a request whose endpoint may not exist yet; maps "not available" to a tagged result for empty states. */
export async function optional<T>(p: Promise<T>): Promise<{ ok: true; data: T } | { ok: false; notAvailable: boolean; message: string }> {
  try {
    return { ok: true, data: await p };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, notAvailable: e.notAvailable, message: e.message };
    return { ok: false, notAvailable: false, message: (e as Error).message };
  }
}
