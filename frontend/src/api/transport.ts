// Transport abstraction: the same REST and WebSocket client code runs against the live backend or the in-browser mock.

export interface SocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export const SOCKET_CONNECTING = 0;
export const SOCKET_OPEN = 1;
export const SOCKET_CLOSING = 2;
export const SOCKET_CLOSED = 3;

export type TransportMode = 'live' | 'mock';

export interface Transport {
  readonly mode: TransportMode;
  fetch(path: string, init?: RequestInit): Promise<Response>;
  openSocket(): SocketLike;
}

export function wsUrl(path = '/ws'): string {
  const loc = typeof window !== 'undefined' ? window.location : null;
  if (!loc) return `ws://127.0.0.1:8765${path}`;
  const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${loc.host}${path}`;
}

export function liveTransport(): Transport {
  return {
    mode: 'live',
    fetch: (path, init) => window.fetch(path, init),
    openSocket: () => new WebSocket(wsUrl()) as unknown as SocketLike,
  };
}

/** Probe the live backend. Resolves true only for a JSON {ok: true} answer within the timeout. */
export async function probeBackend(timeoutMs = 1500): Promise<{ ok: boolean; version?: string }> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await window.fetch('/api/health', { signal: ctrl.signal, headers: { accept: 'application/json' } });
    if (!r.ok) return { ok: false };
    const ct = r.headers.get('content-type') ?? '';
    if (!ct.includes('json')) return { ok: false };
    const j = (await r.json()) as { ok?: boolean; version?: string };
    return { ok: j.ok === true, version: j.version };
  } catch {
    return { ok: false };
  } finally {
    clearTimeout(timer);
  }
}

/** VITE_MOCK=1 forces mock, VITE_MOCK=0 forces live; otherwise dev probes the backend and falls back to mock. */
export function mockSetting(): 'force-mock' | 'force-live' | 'auto' {
  const v = String(import.meta.env.VITE_MOCK ?? '').trim();
  if (v === '1' || v.toLowerCase() === 'true') return 'force-mock';
  if (v === '0' || v.toLowerCase() === 'false') return 'force-live';
  // URL override for manual testing: ?mock=1 / ?mock=0
  if (typeof window !== 'undefined') {
    const q = new URLSearchParams(window.location.search).get('mock');
    if (q === '1') return 'force-mock';
    if (q === '0') return 'force-live';
  }
  return import.meta.env.DEV ? 'auto' : 'force-live';
}
