import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useApp, type AppState } from './store/store';
import type { Layout, Metrics, Part } from './api/types';
import { computeMetrics } from './lib/physics';
import { isCurrent, scoresVisible } from './api/protocol';

export function useParts(): Part[] {
  const parts = useApp((s) => s.dataset.parts);
  const order = useApp((s) => s.dataset.partOrder);
  return useMemo(() => order.map((id) => parts[id]).filter(Boolean), [parts, order]);
}

export function usePartsRecord(): Record<string, Part> {
  return useApp((s) => s.dataset.parts);
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const h = () => setReduced(mq.matches);
    mq.addEventListener?.('change', h);
    return () => mq.removeEventListener?.('change', h);
  }, []);
  return reduced;
}

export interface DisplayMetrics {
  metrics: Metrics | null;
  /** 'backend' = as published; 'local' = local recompute after a pending physical edit (labelled) */
  source: 'backend' | 'local' | 'none';
  /** layout whose poses the metrics belong to */
  layout: Layout | null;
  scoresShown: boolean;
  current: boolean;
}

/** Metrics to show for the displayed layout. Never interpolated; a pending mass edit shows a labelled local recompute. */
export function useDisplayMetrics(): DisplayMetrics {
  const best = useApp((s) => s.solver.best);
  const massEdits = useApp((s) => s.physical.massEdits);
  const parts = useApp((s) => s.dataset.parts);
  const rotations = useApp((s) => s.dataset.rotations);
  const project = useApp((s) => s.dataset.project);
  const settings = useApp((s) => s.goals.settings);
  const newest = useApp((s) => s.conn.newest);
  const applied = useApp((s) => s.conn.appliedClientSeq);
  const sent = useApp((s) => s.conn.lastClientSeqSent);
  return useMemo(() => {
    const scoresShown = scoresVisible({ appliedClientSeq: applied, lastClientSeqSent: sent });
    if (!best) return { metrics: null, source: 'none', layout: null, scoresShown, current: false };
    const current = isCurrent(best, newest);
    const pending = Object.entries(massEdits).filter(([id, e]) => best.poses.some((p) => p.part_id === id) && parts[id]?.mass_kg !== e.mass_kg);
    if (pending.length && rotations.length && best.poses.every((p) => parts[p.part_id])) {
      const size = (project?.enclosure.size_mm as number[] | undefined) ?? [100, 100, 340.5];
      try {
        const local = computeMetrics(
          parts,
          best.poses,
          {
            rotations,
            limits: project?.limits ?? {},
            enclosureZ: [-size[2] / 2, size[2] / 2],
            enclosureVolumeMm3: size[0] * size[1] * size[2],
            targetComMm: settings?.target_com_mm ?? [0, 0, 0],
            compactness: settings?.compactness_definition ?? 'one_end',
          },
          Object.fromEntries(pending.map(([id, e]) => [id, e.mass_kg])),
        );
        // geometry-only metrics stay as the backend published them
        const m: Metrics = {
          ...best.metrics,
          mass_kg: local.mass_kg,
          com_mm: local.com_mm,
          com_error_mm: local.com_error_mm,
          com_box_ok: local.com_box_ok,
          com_box_margin_mm: local.com_box_margin_mm,
          inertia_kgm2: local.inertia_kgm2,
          principal_kgm2: local.principal_kgm2,
          principal_axes: local.principal_axes,
          lambda_max_kgm2: local.lambda_max_kgm2,
          trace_kgm2: local.trace_kgm2,
          products_norm_kgm2: local.products_norm_kgm2,
          kappa: local.kappa,
          tilt_deg: local.tilt_deg,
        };
        return { metrics: m, source: 'local', layout: best, scoresShown, current };
      } catch {
        /* fall through to backend metrics */
      }
    }
    return { metrics: best.metrics, source: 'backend', layout: best, scoresShown, current };
  }, [best, massEdits, parts, rotations, project, settings, newest, applied, sent]);
}

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  notAvailable: boolean;
  loading: boolean;
  reload: () => void;
}

/** Fetch helper: maps "endpoint not available" (404/405/501) to an empty state instead of an error. */
export function useAsync<T>(fn: (() => Promise<T>) | null, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<Omit<AsyncState<T>, 'reload'>>({ data: null, error: null, notAvailable: false, loading: !!fn });
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    const f = fnRef.current;
    if (!f) {
      setState({ data: null, error: null, notAvailable: false, loading: false });
      return;
    }
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    f().then(
      (data) => alive && setState({ data, error: null, notAvailable: false, loading: false }),
      (e: unknown) => {
        if (!alive) return;
        const err = e as { notAvailable?: boolean; message?: string };
        setState({ data: null, error: err?.message ?? String(e), notAvailable: !!err?.notAvailable, loading: false });
      },
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

export function selectDisplayLocked(s: AppState, id: string): boolean {
  return s.physical.lockEdits[id]?.locked ?? s.dataset.parts[id]?.locked ?? false;
}
