import { Canvas } from '@react-three/fiber';
import { GizmoHelper, GizmoViewport, PerformanceMonitor } from '@react-three/drei';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Layout, Metrics, Vec3 } from '../../api/types';
import { badgeText, layoutCoverage, type RenderItem } from '../../api/protocol';
import { SUBSYSTEM_COLORS, SUBSYSTEM_LABELS, STATUS_COLORS, ramp } from '../../lib/colors';
import { TWEEN_LABEL } from '../../lib/copy';
import { useApp, displayMass, type ColorMode } from '../../store/store';
import { useParts, useReducedMotion } from '../../hooks';
import { CameraRig, SceneContent, viewportKeyHandler, type CameraApi, type SceneSpec } from './Scene';
import { TWEEN_MS } from './SceneParts';
import { Toggle } from '../ui';
import { LabelContext, LabelHub, LabelLayer, LabelProjector } from './labels';
import { ErrorBoundary } from '../ErrorBoundary';

export function Legend(props: { mode: ColorMode; parts: { subsystem: string }[]; note?: string }) {
  if (props.mode === 'subsystem') {
    const present = [...new Set(props.parts.map((p) => p.subsystem))].filter((s) => SUBSYSTEM_COLORS[s]);
    return (
      <div className="vp-legend" aria-label="Colour legend: subsystem">
        {present.map((s) => (
          <div key={s} style={{ display: 'contents' }}>
            <span className="swatch" style={{ background: SUBSYSTEM_COLORS[s] }} />
            <span>{SUBSYSTEM_LABELS[s] ?? s}</span>
          </div>
        ))}
      </div>
    );
  }
  if (props.mode === 'status') {
    return (
      <div className="vp-legend" aria-label="Colour legend: status">
        {Object.entries(STATUS_COLORS).map(([k, c]) => (
          <div key={k} style={{ display: 'contents' }}>
            <span className="swatch" style={{ background: c }} />
            <span>{k}</span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="vp-legend" aria-label={`Colour legend: ${props.mode}`}>
      <span className="swatch" style={{ background: `linear-gradient(90deg, ${ramp(0)}, ${ramp(0.5)}, ${ramp(1)})`, width: 60 }} />
      <span>{props.mode === 'mass' ? 'low → high mass' : 'small → large move since previous layout'}</span>
      {props.note ? <span style={{ gridColumn: '1 / span 2' }}>{props.note}</span> : null}
    </div>
  );
}

export function ViewportToolbar(props: { extra?: ReactNode; onFit: () => void }) {
  const v = useApp((s) => s.view);
  const setFlag = useApp((s) => s.setViewFlag);
  const setColorMode = useApp((s) => s.setColorMode);
  return (
    <div className="vp-toolbar" role="toolbar" aria-label="Viewport display options">
      <button type="button" className="btn small" onClick={props.onFit} title="Fit (F)">
        Fit
      </button>
      <Toggle pressed={v.showEnclosure} onChange={(x) => setFlag('showEnclosure', x)} shortcut="E">
        Enclosure
      </Toggle>
      <Toggle pressed={v.showLabels} onChange={(x) => setFlag('showLabels', x)}>
        Labels
      </Toggle>
      <Toggle pressed={v.showCom} onChange={(x) => setFlag('showCom', x)}>
        COM
      </Toggle>
      <Toggle pressed={v.showAxes} onChange={(x) => setFlag('showAxes', x)}>
        Axes
      </Toggle>
      {v.expert ? (
        <>
          <Toggle pressed={v.showBBoxes} onChange={(x) => setFlag('showBBoxes', x)}>
            Boxes
          </Toggle>
          <Toggle pressed={v.showGhost} onChange={(x) => setFlag('showGhost', x)} title="Show unverified candidates as dotted ghosts">
            Ghost
          </Toggle>
        </>
      ) : null}
      <label className="row small" style={{ gap: 4, marginLeft: 6 }}>
        Colour
        <select value={v.colorMode} onChange={(e) => setColorMode(e.target.value as ColorMode)} aria-label="Colour mode" style={{ height: 22 }}>
          <option value="subsystem">Subsystem</option>
          <option value="status">Status</option>
          <option value="mass">Mass</option>
          <option value="displacement">Displacement</option>
        </select>
      </label>
      {props.extra}
    </div>
  );
}

export interface MainViewportProps {
  items: RenderItem[];
  metrics: Metrics | null;
  prevLayout?: Layout | null;
  stage?: 1 | 2;
  testId?: string;
  overlay?: ReactNode;
  toolbarExtra?: ReactNode;
  hideToolbar?: boolean;
  ariaLabel?: string;
  tween?: boolean;
}

/** The main 3D viewport (single canvas, demand frame loop, WebGL2). */
export function MainViewport(props: MainViewportProps) {
  const parts = useApp((s) => s.dataset.parts);
  const partList = useParts();
  const rotations = useApp((s) => s.dataset.rotations);
  const project = useApp((s) => s.dataset.project);
  const settings = useApp((s) => s.goals.settings);
  const view = useApp((s) => s.view);
  const newest = useApp((s) => s.conn.newest);
  const mode = useApp((s) => s.conn.mode);
  const staleReasons = useApp((s) => s.solver.staleReasons);
  const select = useApp((s) => s.select);
  const hover = useApp((s) => s.hover);
  const toggleHidden = useApp((s) => s.toggleHidden);
  const isolate = useApp((s) => s.isolate);
  const showAll = useApp((s) => s.showAll);
  const setFlag = useApp((s) => s.setViewFlag);
  const physical = useApp((s) => s.physical);
  const dataset = useApp((s) => s.dataset);
  const reduced = useReducedMotion();
  const cam = useRef<CameraApi>(null);
  const hub = useMemo(() => new LabelHub(), []);
  const [dpr, setDpr] = useState<number | [number, number]>([1, 2]);
  const [tweening, setTweening] = useState(false);
  const stage = props.stage ?? settings?.stage ?? 1;
  const size = (project?.enclosure.size_mm as Vec3 | undefined) ?? [100, 100, 340.5];
  const solid = props.items.find((i) => i.role === 'best') ?? null;
  const ghost = props.items.find((i) => i.style === 'ghost' && i.role === 'candidate') ?? null;
  const tween = (props.tween ?? true) && !reduced;

  // label the 300 ms pose tween while it runs (metrics never interpolate)
  const lastId = useRef<string | null>(null);
  useEffect(() => {
    const id = solid?.layout.id ?? null;
    if (lastId.current && id && id !== lastId.current && tween) {
      setTweening(true);
      const t = setTimeout(() => setTweening(false), TWEEN_MS + 50);
      lastId.current = id;
      return () => clearTimeout(t);
    }
    lastId.current = id;
  }, [solid?.layout.id, tween]);

  const massOf = useCallback((id: string) => displayMass({ physical, dataset } as never, id), [physical, dataset]);

  const spec: SceneSpec = useMemo(
    () => ({
      items: props.items,
      parts,
      rotations,
      size,
      stage,
      frame: project?.stage2_frame ?? null,
      limits: project?.limits ?? {},
      metrics: props.metrics,
      target: settings?.target_com_mm ?? [0, 0, 0],
      prevLayout: props.prevLayout ?? null,
      massOf,
      view: {
        colorMode: view.colorMode,
        showEnclosure: view.showEnclosure,
        showLabels: view.showLabels,
        showCom: view.showCom,
        showAxes: view.showAxes,
        showBBoxes: view.showBBoxes && view.expert,
        hidden: view.hidden,
        isolated: view.isolated,
        selectedId: view.selectedPartId,
        hoveredId: view.hoveredPartId,
      },
      interactive: true,
      html: true,
      tween,
      onSelect: select,
      onHover: hover,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.items, parts, rotations, size[0], size[1], size[2], stage, project, props.metrics, settings?.target_com_mm, props.prevLayout, massOf, view, tween, select, hover],
  );

  const onKey = viewportKeyHandler(() => cam.current, {
    hide: () => view.selectedPartId && toggleHidden(view.selectedPartId),
    isolate: () => view.selectedPartId && isolate(view.selectedPartId),
    showAll,
    toggleEnclosure: () => setFlag('showEnclosure', !view.showEnclosure),
  });

  const coverage = solid ? layoutCoverage(solid.layout, partList) : { missing: [], removed: [] };
  const helpId = `${props.testId ?? 'vp'}-help`;

  return (
    <div className="stack" style={{ flex: 1, minHeight: 0, gap: 0 }}>
      {props.hideToolbar ? null : <ViewportToolbar onFit={() => cam.current?.fit()} extra={props.toolbarExtra} />}
      <div
        className="viewport-wrap"
        tabIndex={0}
        role="region"
        aria-label={props.ariaLabel ?? '3D viewport'}
        aria-describedby={helpId}
        data-testid={props.testId ?? 'viewport'}
        onKeyDown={onKey}
      >
        <span id={helpId} className="sr-only">
          Keyboard: F fit, 1 to 6 standard views, 0 isometric, arrow keys orbit, H hide selected part, I isolate, Shift+H show all, E enclosure. Parts are listed in the parts list.
        </span>
        <ErrorBoundary label="The 3D viewport">
        <LabelContext.Provider value={hub}>
        <Canvas
          frameloop="demand"
          dpr={dpr}
          gl={{ antialias: true, powerPreference: 'high-performance' }}
          camera={{ position: [420, -560, 300], up: [0, 0, 1], fov: 35, near: 1, far: 20000 }}
          onCreated={(st) => {
            (st.raycaster as unknown as { firstHitOnly: boolean }).firstHitOnly = true;
            st.gl.setClearColor('#26282C');
          }}
          onPointerMissed={() => select(null)}
        >
          <PerformanceMonitor onDecline={() => setDpr(1)} />
          <color attach="background" args={['#26282C']} />
          <CameraRig ref={cam} size={size} fitKey={view.fitRequest} />
          <SceneContent spec={spec} />
          <LabelProjector />
          <GizmoHelper alignment="bottom-right" margin={[56, 56]}>
            <GizmoViewport axisColors={['#F2877A', '#5CC08A', '#5D96F0']} labelColor="#111317" />
          </GizmoHelper>
        </Canvas>
        </LabelContext.Provider>
        </ErrorBoundary>
        <LabelLayer hub={hub} />
        <div className="vp-overlay tl">
          {solid ? (
            <div>
              <span className={`vp-chip ${solid.style === 'stale' ? 'warn' : ''}`} data-testid="layout-badge">
                {badgeText(solid.kind)}
              </span>{' '}
              <span className="vp-chip">{stage === 2 ? 'STAGE 2 ENGINEERING-CONSTRAINED (ASSUMED frame)' : 'STAGE 1 IDEALIZED'}</span>{' '}
              {mode === 'mock' ? <span className="vp-chip warn">MOCK placeholder layout</span> : null}
              {solid.style === 'stale' && staleReasons[solid.layout.id] ? (
                <div>
                  <span className="vp-chip warn">{staleReasons[solid.layout.id]}</span>
                </div>
              ) : null}
              {coverage.missing.length ? (
                <div>
                  <span className="vp-chip warn" data-testid="missing-parts">
                    does not include {coverage.missing.map((p) => p.name).join(', ')}
                  </span>
                </div>
              ) : null}
              {coverage.removed.length ? (
                <div>
                  <span className="vp-chip warn">includes removed part(s) {coverage.removed.join(', ')}</span>
                </div>
              ) : null}
            </div>
          ) : (
            <span className="vp-chip">No validated layout to show</span>
          )}
        </div>
        <div className="vp-overlay tr">
          {ghost ? (
            <div>
              <span className="vp-chip dotted" data-testid="unverified-chip">
                UNVERIFIED candidate (dotted ghost)
              </span>
            </div>
          ) : null}
          {tweening ? (
            <div>
              <span className="vp-chip" data-testid="tween-label">
                {TWEEN_LABEL}
              </span>
            </div>
          ) : null}
          {newest && solid && solid.layout.mass_rev < newest.mass_rev ? (
            <div>
              <span className="vp-chip warn">metrics updating after a mass edit…</span>
            </div>
          ) : null}
        </div>
        <div className="vp-overlay bl">
          <Legend mode={view.colorMode} parts={partList} note={view.colorMode === 'displacement' && !props.prevLayout ? 'no previous layout to compare' : undefined} />
        </div>
        {props.overlay}
      </div>
    </div>
  );
}
