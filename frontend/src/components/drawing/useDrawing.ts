// V2 WS6 engineering drawings: keeps the drawing set in step with the shown layout. The model is rebuilt from the
// layout, its BOM and the parts whenever they change; the current sheet is rebuilt 250 ms after the last change
// (debounced, older builds dropped), reusing its rendered views when only masses changed.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Layout } from '../../api/types';
import type { Bom } from '../../lib/bom';
import { useApp } from '../../store/store';
import { buildDrawingModel, type DrawingModel } from './model';
import { releaseRenderer } from './render';
import { TEMPLATES, type TemplateId } from './sheet';
import { buildSheet, type RenderCache, type SheetContext, type SheetData } from './sheetData';

export const DEBOUNCE_MS = 250;

export interface DrawingSet {
  model: DrawingModel | null;
  data: SheetData | null;
  pending: boolean;
  error: string | null;
  /** build any sheet of the set (for printing all), from the cache when possible */
  build: (index: number) => Promise<SheetData | null>;
}

export function useDrawingSet(args: { layout: Layout | null; bom: Bom | null; template: TemplateId; hidden: boolean; index: number; badge: string; designedAt: string | null }): DrawingSet {
  const parts = useApp((s) => s.dataset.parts);
  const rotations = useApp((s) => s.dataset.rotations);
  const project = useApp((s) => s.dataset.project);
  const model = useMemo(
    () => (args.layout && rotations.length ? buildDrawingModel(args.layout, args.bom, parts, rotations, project) : null),
    [args.layout, args.bom, parts, rotations, project],
  );
  const cache = useRef<RenderCache>(new Map());
  const [data, setData] = useState<SheetData | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const gen = useRef(0);

  const ctxFor = useCallback(
    (m: DrawingModel): SheetContext => ({ model: m, template: TEMPLATES[args.template], hidden: args.hidden, badge: args.badge, designedAt: args.designedAt }),
    [args.template, args.hidden, args.badge, args.designedAt],
  );

  useEffect(() => {
    if (!model) {
      setData(null);
      return;
    }
    const my = ++gen.current;
    const alive = () => gen.current === my;
    const index = Math.min(args.index, model.sheets.length - 1);
    setPending(true);
    const t = setTimeout(() => {
      buildSheet(model.sheets[index], index, ctxFor(model), alive, cache.current).then(
        (d) => {
          if (!alive()) return;
          setPending(false);
          setError(d ? null : 'This sheet could not be laid out on the chosen template.');
          if (d) setData(d);
        },
        (e: unknown) => {
          if (!alive()) return;
          setPending(false);
          setError(`The drawing could not be built: ${(e as Error).message}`);
        },
      );
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [model, args.index, ctxFor]);

  useEffect(() => () => releaseRenderer(), []);

  const build = useCallback(
    async (index: number) => {
      if (!model || index < 0 || index >= model.sheets.length) return null;
      return buildSheet(model.sheets[index], index, ctxFor(model), () => true, cache.current);
    },
    [model, ctxFor],
  );

  return { model, data, pending, error, build };
}
