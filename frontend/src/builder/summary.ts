// V3 CubeSat Builder — the design summary as Markdown: the mission, every requirement with where it came from, the
// architecture with each part's source, the budgets, the key analyses, the compatibility checks, every assumption
// and every source. It repeats the disclaimer: a conceptual design is never flight-ready.
import type { BuilderResponse } from './types';
import type { Analysis } from './analysisTypes';
import { dimsText, num, PICK_TEXT, powerText, priceText, STATUS_TEXT, verdict, withUnit } from './analysisTypes';

const SOURCE_WORDS: Record<string, string> = { user: 'you', statement: 'your description', default: 'default (ASSUMED)', derived: 'derived' };

function cell(s: unknown): string {
  return String(s ?? '—').replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

/** Every assumption the design rests on: defaults taken for "I don't know", and the analyses' own. */
export function assumptions(r: BuilderResponse, a: Analysis): string[] {
  const out = new Set<string>();
  for (const q of r.view.requirements) if (q.source === 'default' && q.note) out.add(`${q.prompt ?? q.key}: ${q.display ?? String(q.value)} — ${q.note}`);
  for (const q of a.open_questions ?? []) out.add(`${q.prompt}: ${q.default} — not answered yet, so the default is used: ${q.why}`);
  for (const id of Object.keys(a.calcs)) for (const s of a.calcs[id].assumptions ?? []) out.add(s);
  return [...out];
}

export function summaryMarkdown(r: BuilderResponse, a: Analysis): string {
  const d = r.design;
  const L: string[] = [];
  L.push(`# ${d.name}`, '');
  L.push(`Design ${d.id}, version ${d.version}; analysis of version ${a.design_version} (${a.computed_at}, engine ${a.engine}).`, '');
  if (d.statement) L.push(`> ${d.statement}`, '');
  L.push(`**${a.disclaimer}**`, '');
  L.push('## Requirements', '', '| Requirement | Value | From |', '|---|---|---|');
  for (const q of r.view.requirements) L.push(`| ${cell(q.prompt ?? q.key)} | ${cell(q.display ?? q.value)} | ${SOURCE_WORDS[q.source] ?? q.source} |`);
  L.push('', `## Architecture — ${a.size_label}`, '', a.size_why, '', `Orbit: ${num(a.orbit.alt_km)} km, ${a.orbit.sso ? 'sun-synchronous, ' : ''}${num(a.orbit.inc_deg)}° inclination. ${a.orbit.why}`, '');
  L.push('| Subsystem | Part | Qty | Mass | Size | Power | Price | Status | Source |', '|---|---|---|---|---|---|---|---|---|');
  for (const s of a.slots) {
    const p = a.picks[s.id];
    if (!p || !p.items.length) continue;
    for (const it of p.items) {
      L.push(
        `| ${cell(p.label)} | ${cell(it.name)} | ${it.qty} | ${it.mass_kg != null ? `${num(it.mass_kg)} kg` : 'not published'} | ${cell(dimsText(it.dims_mm))} | ${cell(powerText(it.power_w))} | ${cell(priceText(it.price))} | ${PICK_TEXT[p.status]}${p.place === 'external' ? ', not packed' : ''} | ${it.url ?? (it.placeholder ? 'your answers' : '—')} |`,
      );
    }
  }
  if (a.missing_hardware.length) L.push('', `Also needed (not in the catalog): ${a.missing_hardware.join('; ')}.`);
  L.push('', '## Budgets', '');
  const m = a.calcs['budget.mass'];
  if (m) L.push(`- Mass: ${withUnit(m.value, 'kg')} (${num(m.with_margin_kg)} kg with the ${num(m.margin_pct)} % design margin) against ${num(m.limit_kg)} kg.`);
  const pm = a.calcs['power.margin'];
  if (pm) L.push(`- Power: ${pm.value == null ? 'not computed' : withUnit(pm.value, '%')} energy margin on the worst day.`);
  const db = a.calcs['budget.data'];
  if (db) L.push(`- Data: ${withUnit(db.value, '%')} of the daily data returned.`);
  const cost = a.calcs['budget.cost'];
  if (cost) L.push(`- Cost: ${cost.explain}`);
  L.push('', '## Analyses', '');
  for (const g of a.groups) {
    L.push(`### ${g.label}`, '');
    for (const id of g.calcs) {
      const c = a.calcs[id];
      if (!c) continue;
      const v = verdict(c);
      const shown = c.value == null ? (c.missing ? `not computed — needs ${c.missing}` : (typeof c.text === 'string' ? c.text : '—')) : withUnit(c.value, c.unit);
      L.push(`- ${c.label}: **${shown}**${v === true ? ' (meets)' : v === false ? ' (NOT MET)' : ''}${c.explain ? ` — ${c.explain}` : ''}${c.equation ? ` [${c.equation}]` : ''}`);
    }
    L.push('');
  }
  L.push('## Compatibility', '');
  for (const s of ['incompatible', 'unknown', 'assumptions', 'compatible'] as const) {
    const cs = a.checks.filter((c) => c.status === s);
    if (!cs.length) continue;
    L.push(`### ${STATUS_TEXT[s]} (${cs.length})`, '');
    for (const c of cs) L.push(`- ${c.title}: ${c.detail}${c.fix ? ` (fix: ${c.fix})` : ''}`);
    L.push('');
  }
  L.push('## Assumptions', '');
  for (const s of assumptions(r, a)) L.push(`- ${s}`);
  L.push('', '## Sources', '');
  const used = new Set<string>();
  for (const id of Object.keys(a.calcs)) for (const k of a.calcs[id].refs ?? []) used.add(k);
  for (const k of [...used].sort()) {
    const ref = a.refs[k];
    if (ref) L.push(`- ${ref.title} — ${ref.publisher}. ${ref.url} (accessed ${ref.accessed})`);
  }
  L.push('', 'Part data: each part above links to the maker page it was read from (catalog compiled 2026-10-25).', '');
  return L.join('\n');
}
