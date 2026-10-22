// Typed REST client for docs/api-contract.md §3.
import type { Transport } from './transport';
import type {
  Attribution,
  Benchmarks,
  CadStatus,
  FidelityResult,
  FidelitySummary,
  IdeaMap,
  Layout,
  LayoutSummary,
  MfgResult,
  Pareto,
  Part,
  ProjectSnapshot,
  Proof,
  RunAction,
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
