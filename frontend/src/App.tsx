import { Tabs, Tooltip } from 'radix-ui';
import { lazy, Suspense, useEffect } from 'react';
import { useApp, type TabId } from './store/store';
import { DropZone, LiveRegion, MockBanner, StatusBar, TopBar } from './components/Shell';
import { UnitsDialog } from './components/UnitsDialog';
import { OverviewTab } from './tabs/Overview';
import { ErrorBoundary } from './components/ErrorBoundary';

const ComponentsTab = lazy(() => import('./tabs/Components').then((m) => ({ default: m.ComponentsTab })));
const OptimizationTab = lazy(() => import('./tabs/Optimization').then((m) => ({ default: m.OptimizationTab })));
const PhysicsTab = lazy(() => import('./tabs/Physics').then((m) => ({ default: m.PhysicsTab })));
const ComparisonTab = lazy(() => import('./tabs/Comparison').then((m) => ({ default: m.ComparisonTab })));
const SizeStudyTab = lazy(() => import('./tabs/SizeStudy').then((m) => ({ default: m.SizeStudyTab })));
const ExplainTab = lazy(() => import('./tabs/Explain').then((m) => ({ default: m.ExplainTab })));
const EngineeringTab = lazy(() => import('./tabs/Engineering').then((m) => ({ default: m.EngineeringTab })));
const HardwareTab = lazy(() => import('./tabs/Hardware').then((m) => ({ default: m.HardwareTab })));
const BomTab = lazy(() => import('./tabs/Bom').then((m) => ({ default: m.BomTab })));
const DrawingsTab = lazy(() => import('./tabs/Drawings').then((m) => ({ default: m.DrawingsTab })));
const ManufacturableTab = lazy(() => import('./tabs/Manufacturable').then((m) => ({ default: m.ManufacturableTab })));
const CadValidationTab = lazy(() => import('./tabs/CadValidation').then((m) => ({ default: m.CadValidationTab })));
const ResultsTab = lazy(() => import('./tabs/Results').then((m) => ({ default: m.ResultsTab })));

export const TABS: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'components', label: 'Components' },
  { id: 'optimization', label: 'Optimization' },
  { id: 'physics', label: 'Physics' },
  { id: 'comparison', label: 'Algorithm Comparison' },
  { id: 'size', label: 'Size Study' },
  { id: 'explain', label: 'Explain' },
  { id: 'engineering', label: 'Engineering Constraints' },
  { id: 'hardware', label: 'Mounting Hardware' },
  { id: 'bom', label: 'Bill of Materials' },
  { id: 'drawings', label: 'Drawings' },
  { id: 'manufacturable', label: 'Manufacturable Design' },
  { id: 'cad', label: 'CAD Validation' },
  { id: 'results', label: 'Results & Export' },
];

function TabBody({ id }: { id: TabId }) {
  switch (id) {
    case 'overview':
      return <OverviewTab />;
    case 'components':
      return <ComponentsTab />;
    case 'optimization':
      return <OptimizationTab />;
    case 'physics':
      return <PhysicsTab />;
    case 'comparison':
      return <ComparisonTab />;
    case 'size':
      return <SizeStudyTab />;
    case 'explain':
      return <ExplainTab />;
    case 'engineering':
      return <EngineeringTab />;
    case 'hardware':
      return <HardwareTab />;
    case 'bom':
      return <BomTab />;
    case 'drawings':
      return <DrawingsTab />;
    case 'manufacturable':
      return <ManufacturableTab />;
    case 'cad':
      return <CadValidationTab />;
    case 'results':
      return <ResultsTab />;
  }
}

export function App() {
  const tab = useApp((s) => s.view.tab);
  const setTab = useApp((s) => s.setTab);
  const expert = useApp((s) => s.view.expert);
  useEffect(() => {
    document.documentElement.dataset.density = expert ? 'expert' : 'beginner';
  }, [expert]);
  return (
    <Tooltip.Provider delayDuration={250}>
      <div className="app">
        <MockBanner />
        <TopBar />
        <Tabs.Root value={tab} onValueChange={(v) => setTab(v as TabId)} asChild>
          <div style={{ display: 'contents' }}>
            <Tabs.List className="tabs-list" aria-label="Workspace tabs">
              {TABS.map((t) => (
                <Tabs.Trigger key={t.id} value={t.id} data-testid={`tab-trigger-${t.id}`}>
                  {t.label}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
            <main className="tab-content" style={{ minHeight: 0 }}>
              {TABS.map((t) => (
                <Tabs.Content key={t.id} value={t.id} className="tab-content" style={{ height: '100%' }} forceMount={undefined}>
                  {tab === t.id ? (
                    <ErrorBoundary label={`The ${t.label} tab`} resetKey={tab}>
                      <Suspense fallback={<div className="tab-scroll muted">Loading…</div>}>
                        <TabBody id={t.id} />
                      </Suspense>
                    </ErrorBoundary>
                  ) : null}
                </Tabs.Content>
              ))}
            </main>
          </div>
        </Tabs.Root>
        <StatusBar />
      </div>
      <UnitsDialog />
      <DropZone />
      <LiveRegion />
    </Tooltip.Provider>
  );
}
