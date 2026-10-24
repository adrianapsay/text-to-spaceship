import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const GEN = resolve(here, '.generated');

/** Write a binary STL box generated at test time (never seen during development). */
function writeBoxStl(name: string, size: [number, number, number]): string {
  const [a, b, c] = size;
  const v = [
    [0, 0, 0], [a, 0, 0], [a, b, 0], [0, b, 0],
    [0, 0, c], [a, 0, c], [a, b, c], [0, b, c],
  ];
  const f = [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
  ];
  const buf = Buffer.alloc(84 + f.length * 50);
  buf.writeUInt32LE(f.length, 80);
  f.forEach((t, i) => t.forEach((vi, j) => v[vi].forEach((x, k) => buf.writeFloatLE(x, 84 + i * 50 + 12 + (j * 3 + k) * 4))));
  mkdirSync(GEN, { recursive: true });
  const p = resolve(GEN, name);
  writeFileSync(p, buf);
  return p;
}

async function openApp(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('/');
  await expect(page.getByTestId('mock-banner')).toBeVisible();
  await expect(page.getByTestId('backend-status')).toContainText('connected');
  await expect(page.getByTestId('parts-list').getByRole('option')).toHaveCount(19);
  await expect(page.getByTestId('layout-badge')).toHaveText('VALIDATED');
  return errors;
}

test('app loads in mock mode with a WebGL2 viewport and labelled metrics', async ({ page }) => {
  const errors = await openApp(page);
  const canvas = page.getByTestId('overview-viewport').locator('canvas');
  await expect(canvas).toBeVisible();
  const gl2 = await canvas.evaluate((c: HTMLCanvasElement) => !!c.getContext('webgl2'));
  expect(gl2).toBe(true);
  // something other than the background colour is drawn
  const png = await canvas.screenshot();
  expect(png.byteLength).toBeGreaterThan(5000);
  await expect(page.getByTestId('metric-mass')).toContainText('2.916');
  await expect(page.getByTestId('metric-space')).toContainText('MOCK');
  await expect(page.getByTestId('algorithm-chip')).toContainText('Algorithm in use');
  expect(errors).toEqual([]);
});

test('all 14 tabs switch and keep the MOCK DATA banner', async ({ page }) => {
  const errors = await openApp(page);
  const tabs: [string, string][] = [
    ['components', 'tab-components'],
    ['optimization', 'tab-optimization'],
    ['physics', 'tab-physics'],
    ['comparison', 'tab-comparison'],
    ['size', 'tab-size'],
    ['explain', 'tab-explain'],
    ['engineering', 'tab-engineering'],
    ['hardware', 'tab-hardware'],
    ['bom', 'tab-bom'],
    ['drawings', 'tab-drawings'],
    ['manufacturable', 'tab-manufacturable'],
    ['cad', 'tab-cad'],
    ['results', 'tab-results'],
    ['overview', 'tab-overview'],
  ];
  for (const [id, content] of tabs) {
    await page.getByTestId(`tab-trigger-${id}`).click();
    await expect(page.getByTestId(content)).toBeVisible();
    await expect(page.getByTestId('mock-banner')).toBeVisible();
  }
  // a few tab-specific checks: empty states instead of fake data, required labels
  await page.getByTestId('tab-trigger-size').click();
  await expect(page.getByText('No Size Study results yet')).toBeVisible();
  await page.getByTestId('tab-trigger-cad').click();
  await expect(page.getByTestId('cad-card')).toHaveText('FUSION 360 VALIDATION: NOT CONFIGURED');
  await page.getByTestId('tab-trigger-explain').click();
  await expect(page.getByTestId('idea-map')).toBeVisible();
  await page.getByTestId('explain-selector').click();
  await expect(page.getByTestId('sweep-space')).toBeVisible();
  await page.getByTestId('explain-proof').click();
  await expect(page.getByTestId('proof-markdown')).toContainText('Lemma 1');
  await page.getByTestId('tab-trigger-manufacturable').click();
  await expect(page.getByText('manufacturing concept — assumed cost model, not a quote', { exact: false }).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('bill of materials and drawings: a MOCK BOM linked to the 3D view, a sheet with views, balloons and parts list', async ({ page }) => {
  const errors = await openApp(page);
  await page.getByTestId('tab-trigger-bom').click();
  const table = page.getByTestId('bom-table');
  await expect(table).toBeVisible();
  await expect(page.getByTestId('tab-bom').getByText('MOCK', { exact: true }).first()).toBeVisible();
  await expect(table.locator('tbody tr[data-testid^="bom-row-"]')).toHaveCount(19);
  await expect(page.getByTestId('bom-total')).toContainText('2,916.0'); // the layout's total mass (2.916 kg)
  await expect(page.getByTestId('bom-totals')).toContainText('= layout mass');
  await expect(page.getByTestId('bom-viewport').locator('canvas')).toBeVisible();
  // a row selects its part in the 3D view (the store's selection), and the row is marked selected
  await page.getByTestId('bom-row-7').click();
  await expect(page.getByTestId('bom-row-7')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('bom-selection')).toContainText('item 7');
  const sel = await page.evaluate(() => (window as unknown as { __t2s: { store: { getState: () => { view: { selectedPartId: string | null } } } } }).__t2s.store.getState().view.selectedPartId);
  expect(sel).toBe('p07');
  // selecting in the 3D view (store) highlights the row
  await page.evaluate(() => (window as unknown as { __t2s: { store: { getState: () => { select: (id: string) => void } } } }).__t2s.store.getState().select('p02'));
  await expect(page.getByTestId('bom-row-2')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('bom-row-7')).toHaveAttribute('aria-selected', 'false');

  await page.getByTestId('tab-trigger-drawings').click();
  const sheet = page.getByTestId('drawing-sheet');
  await expect(sheet).toBeVisible({ timeout: 30_000 });
  await expect(sheet.locator('image[data-view]')).toHaveCount(4, { timeout: 30_000 }); // front, top, left, isometric
  await expect(sheet.locator('[data-field="drawingNo"]')).toContainText('T2S-L-MOCK-0001-000');
  await expect(sheet.locator('[data-field="scale"]')).toContainText('1:2');
  await expect(sheet.locator('[data-testid="drawing-parts-list"] [data-item]')).toHaveCount(19);
  const balloons = await sheet.locator('[data-testid="drawing-balloons"] [data-item]').evaluateAll((els) => els.map((e) => Number(e.getAttribute('data-item'))));
  expect(balloons.length).toBeGreaterThan(10);
  expect(new Set(balloons).size).toBe(balloons.length); // each item once
  expect(balloons.every((n) => n >= 1 && n <= 19)).toBe(true); // numbered like the BOM
  // the alternative template redraws the sheet in third-angle projection
  await page.getByTestId('template-select').selectOption('ansi-b');
  await expect(sheet.locator('[data-view-label="right"]')).toBeVisible({ timeout: 30_000 });
  await expect(sheet.locator('[data-field="size"]')).toContainText('B');
  await page.getByTestId('template-select').selectOption('iso-a3');
  expect(errors).toEqual([]);
});

test('a goal slider moves by keyboard with aria-valuetext and stays separate from physics', async ({ page }) => {
  await openApp(page);
  const slider = page.locator('#goal-balance');
  await slider.focus();
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight');
  await expect(slider).toHaveAttribute('aria-valuetext', '30 percent priority');
  await expect(page.locator('#preset-select')).toHaveValue('custom');
  await expect(page.getByTestId('status-bar')).toContainText('in sync');
  const state = await page.evaluate(() => {
    const s = (window as unknown as { __t2s: { store: { getState: () => { goals: { settings: { sliders: { balance: number } } }; physical: { massEdits: object } } } } }).__t2s.store.getState();
    return { balance: s.goals.settings.sliders.balance, massEdits: Object.keys(s.physical.massEdits).length };
  });
  expect(state).toEqual({ balance: 30, massEdits: 0 });
  // feasibility is greyed out in Stage 1 with an explanation
  await expect(page.locator('#goal-feasibility')).toBeDisabled();
  await expect(page.getByText('Stage 1 is idealized; switch to Stage 2 to work on physical feasibility.')).toBeVisible();
});

test('add a part: units dialog (inch warning) → part listed → old layout badged → Re-run', async ({ page }) => {
  await openApp(page);
  // 80 × 80 × 22 mm battery-like box written in inches: 3.15 × 3.15 × 0.866
  const file = writeBoxStl('e2e_inch_box.stl', [3.15, 3.15, 0.866]);
  await page.getByTestId('file-input').setInputFiles(file);
  const dialog = page.getByTestId('units-dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('e2e_inch_box');
  await expect(dialog.getByRole('alert').first()).toContainText('inches');
  await expect(page.getByTestId('units-mm')).toBeChecked();
  await page.getByTestId('units-in').check();
  await expect(page.getByTestId('units-preview')).toContainText('80.0 × 80.0 × 22.0');
  await page.getByTestId('units-confirm').click();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId('parts-list').getByRole('option')).toHaveCount(20);
  await expect(page.getByTestId('part-e2e_inch_box')).toBeVisible();
  // non-blocking "detail study running" indicator for the new part (WS study.update, study "fidelity")
  await expect(page.getByTestId('part-e2e_inch_box').locator('[data-testid^="fidelity-running-"]')).toBeVisible();
  // the displayed layout was validated for the previous parts
  await expect(page.getByTestId('layout-badge')).toHaveText('VALIDATED FOR PREVIOUS INPUTS');
  await expect(page.getByTestId('missing-parts')).toContainText('does not include e2e_inch_box');
  await expect(page.getByTestId('rerun-bar')).toBeVisible();
  // the detail-level study runs in the background for the new part (non-blocking indicator or done)
  await page.getByTestId('rerun').click();
  await expect(page.getByTestId('layout-badge')).toHaveText('VALIDATED', { timeout: 20_000 });
  await expect(page.getByTestId('missing-parts')).toHaveCount(0);
  await expect(page.getByTestId('metric-mass')).toContainText('3.296'); // 2.916 + 0.380 (0.08·0.08·0.022 m³ × 2,700 kg/m³)
});
