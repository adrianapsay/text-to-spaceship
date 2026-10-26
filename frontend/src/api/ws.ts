// WebSocket client: envelope framing, hello → snapshot, reconnection with exponential backoff (250 ms → 5 s).
import type { Envelope, Revs } from './types';
import { SOCKET_OPEN, type SocketLike, type Transport } from './transport';

export type WsState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface WsClientOptions {
  transport: Transport;
  onEnvelope: (env: Envelope) => void;
  onState: (state: WsState, info: { attempt: number; nextDelayMs: number | null }) => void;
  /** called right before hello so the session can reset per-connection counters */
  onNewConnection: () => void;
  /** values for outgoing envelopes */
  getContext: () => { epoch: number | null; revs: Revs; appliedClientSeq: number };
  /** whether the client wants layout.candidate messages (Expert ghosts) */
  wantCandidates: () => boolean;
  /** V3: the server closed with 4001 because the app switched to another project (the page reloads) */
  onProjectSwitched?: () => void;
  minBackoffMs?: number;
  maxBackoffMs?: number;
  pingIntervalMs?: number;
}

export function backoffDelay(attempt: number, min = 250, max = 5000): number {
  return Math.min(max, min * 2 ** Math.max(0, attempt));
}

export class WsClient {
  private sock: SocketLike | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;
  private outSeq = 0;
  private readonly o: Required<Omit<WsClientOptions, 'transport' | 'onEnvelope' | 'onState' | 'onNewConnection' | 'getContext' | 'wantCandidates' | 'onProjectSwitched'>> &
    WsClientOptions;

  constructor(opts: WsClientOptions) {
    this.o = { minBackoffMs: 250, maxBackoffMs: 5000, pingIntervalMs: 15000, ...opts };
  }

  get isOpen(): boolean {
    return !!this.sock && this.sock.readyState === SOCKET_OPEN;
  }

  connect(): void {
    this.stopped = false;
    this.open();
  }

  close(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.timer = null;
    this.pingTimer = null;
    const s = this.sock;
    this.sock = null;
    if (s) {
      s.onclose = null;
      s.onmessage = null;
      s.onerror = null;
      try {
        s.close(1000, 'client closing');
      } catch {
        /* ignore */
      }
    }
    this.o.onState('closed', { attempt: this.attempt, nextDelayMs: null });
  }

  /** Force a reconnect (used by tests and the status bar "reconnect" button). */
  reconnectNow(): void {
    if (this.sock) {
      try {
        this.sock.close(4000, 'reconnect requested');
      } catch {
        /* ignore */
      }
    } else this.open();
  }

  private open(): void {
    if (this.stopped) return;
    this.o.onState(this.attempt === 0 ? 'connecting' : 'reconnecting', { attempt: this.attempt, nextDelayMs: null });
    let s: SocketLike;
    try {
      s = this.o.transport.openSocket();
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.sock = s;
    s.onopen = () => {
      this.attempt = 0;
      this.outSeq = 0;
      this.o.onNewConnection();
      this.o.onState('open', { attempt: 0, nextDelayMs: null });
      this.send('hello', { last_epoch: this.o.getContext().epoch, want_candidates: this.o.wantCandidates() });
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => this.send('ping', {}), this.o.pingIntervalMs);
    };
    s.onmessage = (ev) => {
      let env: Envelope;
      try {
        env = JSON.parse(String(ev.data)) as Envelope;
      } catch {
        return;
      }
      if (!env || typeof env !== 'object' || typeof env.type !== 'string') return;
      this.o.onEnvelope(env);
    };
    s.onerror = () => {
      /* onclose follows */
    };
    s.onclose = (ev) => {
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = null;
      if (this.sock === s) this.sock = null;
      if (ev?.code === 4001 && this.o.onProjectSwitched) {
        this.stopped = true;                            // everything this page holds belongs to the old project
        this.o.onProjectSwitched();
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = backoffDelay(this.attempt, this.o.minBackoffMs, this.o.maxBackoffMs);
    this.attempt += 1;
    this.o.onState('reconnecting', { attempt: this.attempt, nextDelayMs: delay });
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.open();
    }, delay);
  }

  /** Send one envelope; returns false when the socket is not open (the caller keeps the intent for re-send). */
  send(type: string, payload: unknown): boolean {
    if (!this.sock || this.sock.readyState !== SOCKET_OPEN) return false;
    const ctx = this.o.getContext();
    this.outSeq += 1;
    const env: Envelope = {
      v: 1,
      type,
      seq: this.outSeq,
      epoch: ctx.epoch ?? 0,
      parts_rev: ctx.revs.parts_rev,
      constraint_rev: ctx.revs.constraint_rev,
      mass_rev: ctx.revs.mass_rev,
      weights_rev: ctx.revs.weights_rev,
      applied_client_seq: ctx.appliedClientSeq,
      ts: new Date().toISOString(),
      payload,
    };
    try {
      this.sock.send(JSON.stringify(env));
      return true;
    } catch {
      return false;
    }
  }
}

/**
 * Leading + trailing throttle per control (≤ 20 Hz by default). `push` sends at once when the interval has
 * elapsed, otherwise schedules one trailing send with the latest value. `flush` cancels the trailing send and
 * sends the given value immediately (used for `commit` on release).
 */
export class Throttle<T> {
  private last = -Infinity;
  private pending: T | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private readonly sendFn: (v: T, commit: boolean) => void;
  private readonly intervalMs: number;
  private readonly now: () => number;

  constructor(sendFn: (v: T, commit: boolean) => void, intervalMs = 50, now: () => number = () => performance.now()) {
    this.sendFn = sendFn;
    this.intervalMs = intervalMs;
    this.now = now;
  }

  push(v: T): void {
    const t = this.now();
    if (t - this.last >= this.intervalMs && !this.timer) {
      this.last = t;
      this.sendFn(v, false);
      return;
    }
    this.pending = v;
    if (!this.timer) {
      const wait = Math.max(0, this.intervalMs - (t - this.last));
      this.timer = setTimeout(() => {
        this.timer = null;
        if (this.pending !== null) {
          const p = this.pending;
          this.pending = null;
          this.last = this.now();
          this.sendFn(p, false);
        }
      }, wait);
    }
  }

  flush(v: T): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.pending = null;
    this.last = this.now();
    this.sendFn(v, true);
  }

  cancel(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.pending = null;
  }
}
