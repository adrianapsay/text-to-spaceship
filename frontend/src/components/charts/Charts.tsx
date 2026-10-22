import { useEffect, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import * as Plot from '@observablehq/plot';

/** uPlot line chart wrapper (convergence, anytime curves, size study). Resizes with its container. */
export function UPlotChart(props: { options: Omit<uPlot.Options, 'width' | 'height'>; data: uPlot.AlignedData; height?: number; ariaLabel: string; testId?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof window === 'undefined') return;
    if (!(window as unknown as { matchMedia?: unknown }).matchMedia) return;
    let u: uPlot | null = null;
    try {
      u = new uPlot({ ...props.options, width: Math.max(200, el.clientWidth), height: props.height ?? 220 } as uPlot.Options, props.data, el);
    } catch {
      return;
    }
    plot.current = u;
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => u?.setSize({ width: Math.max(200, el.clientWidth), height: props.height ?? 220 })) : null;
    ro?.observe(el);
    return () => {
      ro?.disconnect();
      u?.destroy();
      plot.current = null;
    };
    // options identity changes rebuild the chart; data updates use setData
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.options, props.height]);
  useEffect(() => {
    plot.current?.setData(props.data);
  }, [props.data]);
  return <div ref={ref} role="img" aria-label={props.ariaLabel} data-testid={props.testId} />;
}

/** Observable Plot wrapper (scatter, strip plots, heat maps). */
export function PlotFigure(props: { options: Plot.PlotOptions; ariaLabel: string; testId?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let node: (SVGSVGElement | HTMLElement) | null = null;
    try {
      node = Plot.plot({ style: { background: 'transparent', color: 'currentColor', fontFamily: 'Segoe UI, system-ui, sans-serif', fontSize: '11px' }, ...props.options });
      el.replaceChildren(node);
    } catch (e) {
      el.textContent = `chart could not be drawn: ${(e as Error).message}`;
    }
    return () => node?.remove();
  }, [props.options]);
  return <div ref={ref} className="plot-figure" role="img" aria-label={props.ariaLabel} data-testid={props.testId} />;
}

export const chartAxis = (label: string, extra: Partial<uPlot.Axis> = {}): uPlot.Axis => ({
  label,
  stroke: 'currentColor',
  grid: { stroke: 'rgba(127,127,127,0.25)', width: 1 },
  ticks: { stroke: 'rgba(127,127,127,0.4)', width: 1 },
  font: '11px Segoe UI',
  labelFont: '11px Segoe UI',
  ...extra,
});
