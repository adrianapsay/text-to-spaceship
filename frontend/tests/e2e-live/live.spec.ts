import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Live backend: every number on screen comes from the real optimiser and validator.
const here = dirname(fileURLToPath(import.meta.url));
const GEN = resolve(here, '.generated');

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

async function openLive(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('/');
  await expect(page.getByTestId('backend-status')).toContainText('connected');
  await expect(page.getByTestId('mock-banner')).toHaveCount(0);
  await expect(page.getByTestId('parts-list').getByRole('option')).toHaveCount(19);
  await expect(page.getByTestId('layout-badge')).toHaveText('VALIDATED');
  return errors;
}

test('live: the real optimiser streams a validated layout with real metrics', async ({ page }) => {
  const errors = await openLive(page);
  await expect(page.getByTestId('metric-mass')).toContainText('2.916');
  await expect(page.getByTestId('metric-space')).not.toContainText('MOCK');
  await expect(page.getByTestId('algorithm-chip')).toContainText('Hybrid BRKGA + box decoder');
  await expect(page.getByTestId('status-bar')).toContainText('SEARCHING');
  const canvas = page.getByTestId('overview-viewport').locator('canvas');
  await expect(canvas).toBeVisible();
  expect(errors).toEqual([]);
});

test('live: a slider edit is acknowledged and the layout stays validated', async ({ page }) => {
  await openLive(page);
  const slider = page.locator('#goal-balance');
  await slider.focus();
  for (let i = 0; i < 10; i++) await page.keyboard.press('ArrowRight');
  await expect(slider).toHaveAttribute('aria-valuetext', '35 percent priority');
  await expect(page.getByTestId('status-bar')).toContainText('in sync');
  await expect(page.getByTestId('layout-badge')).toHaveText('VALIDATED');
});

test('live: proof tab shows the backend certificate; CAD stays NOT CONFIGURED', async ({ page }) => {
  await openLive(page);
  await page.getByTestId('tab-trigger-explain').click();
  await page.getByTestId('explain-proof').click();
  await expect(page.getByTestId('proof-markdown')).toContainText('Proof that layout L-');
  await expect(page.getByTestId('proof-markdown')).toContainText('Lemma 1');
  await page.getByTestId('tab-trigger-cad').click();
  await expect(page.getByTestId('cad-card')).toHaveText('FUSION 360 VALIDATION: NOT CONFIGURED');
});

test('live: a file added later (in inches) is analysed and joins the next validated layout', async ({ page }) => {
  await openLive(page);
  const file = writeBoxStl('friend_box.stl', [1.5, 1.2, 0.8]);   // 38.1 × 30.48 × 20.32 mm
  await page.getByTestId('file-input').setInputFiles(file);
  const dialog = page.getByTestId('units-dialog');
  await expect(dialog).toBeVisible();
  await page.getByTestId('units-in').check();
  await page.getByTestId('units-confirm').click();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId('parts-list').getByRole('option')).toHaveCount(20);
  await expect(page.getByTestId('part-friend_box')).toBeVisible();
  // the new part is in the next current validated layout (the backend restarts the search on its own)
  await expect(page.getByTestId('layout-badge')).toHaveText('VALIDATED', { timeout: 150_000 });
  await expect(page.getByTestId('missing-parts')).toHaveCount(0, { timeout: 150_000 });
  // 2.916 kg + 38.1 × 30.48 × 20.32 mm³ × 2,700 kg/m³ = 2.916 + 0.0637 = 2.980 kg
  await expect(page.getByTestId('metric-mass')).toContainText('2.980', { timeout: 150_000 });
});
