// V3 CubeSat Builder — Design Summary: the design on one page, and as a Markdown file to keep (requirements and where
// each came from, the architecture with its sources, budgets, analyses, checks, assumptions and sources).
import { useMemo } from 'react';
import type { BuilderResponse } from './types';
import type { Analysis } from './analysisTypes';
import { STATUS_TEXT, withUnit } from './analysisTypes';
import { assumptions, summaryMarkdown } from './summary';
import { Button, KV, Notice, Panel } from '../components/ui';
import { orbitText } from './ArchitectureView';
import { slug } from './slug';

export function SummarySection(props: { r: BuilderResponse; a: Analysis; stale: boolean }) {
  const { r, a } = props;
  const md = useMemo(() => summaryMarkdown(r, a), [r, a]);
  const assumed = useMemo(() => assumptions(r, a), [r, a]);
  const download = () => {
    const url = URL.createObjectURL(new Blob([md], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${slug(r.design.name)}-v${r.design.version}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const m = a.calcs['budget.mass'];
  const c = a.check_summary.counts;
  return (
    <div className="stack" data-testid="summary">
      {props.stale ? <Notice tone="info">Recomputing — this summary is of design version {a.design_version}.</Notice> : null}
      <Notice tone="warn">{a.disclaimer}</Notice>
      <div className="grid-2">
        <Panel title={r.design.name} caption={`${a.size_label} · ${orbitText(a.orbit)}`} right={<Button size="small" onClick={download} data-testid="download-summary">Download (Markdown)</Button>}>
          <KV
            rows={[
              ['Mission', r.design.statement || '—'],
              ['Size', `${a.size_label} — ${a.size_why}`],
              ['Mass', m ? `${withUnit(m.value, 'kg')} (${withUnit(m.with_margin_kg, 'kg')} with margin) of ${withUnit(m.limit_kg, 'kg')}` : '—'],
              ['Power margin', withUnit(a.calcs['power.margin']?.value, '%')],
              ['Data returned', a.calcs['budget.data'] ? withUnit(a.calcs['budget.data'].value, '%') : '—'],
              ['Listed prices', a.calcs['budget.cost']?.explain ?? '—'],
              ['Checks', (['incompatible', 'unknown', 'assumptions', 'compatible'] as const).map((s) => `${c[s]} ${STATUS_TEXT[s].toLowerCase()}`).join(' · ')],
            ]}
          />
        </Panel>
        <Panel title="Assumptions to verify" caption={`${assumed.length} — each must be confirmed before the design can be relied on`}>
          <ul className="small" style={{ margin: '0 0 0 16px' }}>
            {assumed.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
