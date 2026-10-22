import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Layout, ProjectSnapshot } from '../../src/api/types';
import { MockBackend, type MockFixtures } from '../../src/mock/mockBackend';

export const FIXTURE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../../public/mock-fixtures');

export function loadFixtures(): MockFixtures {
  const project = JSON.parse(readFileSync(resolve(FIXTURE_DIR, 'project.json'), 'utf8')) as ProjectSnapshot;
  const layouts = (JSON.parse(readFileSync(resolve(FIXTURE_DIR, 'layouts.json'), 'utf8')) as { layouts: Layout[] }).layouts;
  return { project, layouts };
}

export function toArrayBuffer(b: Buffer): ArrayBuffer {
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
}

export function makeMockBackend(): MockBackend {
  return new MockBackend(loadFixtures(), {
    meshLoader: async (id) => toArrayBuffer(readFileSync(resolve(FIXTURE_DIR, 'meshes', `${id}.bin`))),
    latencyMs: 0,
    searchIntervalMs: 20,
    fidelityStepMs: 5,
    searchBudget: 5,
  });
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function waitFor(pred: () => boolean, timeoutMs = 3000, stepMs = 5): Promise<void> {
  const t0 = Date.now();
  while (!pred()) {
    if (Date.now() - t0 > timeoutMs) throw new Error('waitFor timed out');
    await sleep(stepMs);
  }
}
