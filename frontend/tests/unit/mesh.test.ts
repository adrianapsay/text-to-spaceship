import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { decodeMesh, encodeMesh } from '../../src/api/rest';
import { boxTriangles, buildBinaryStl, canonicalise, checkMesh, massProps, parseStl } from '../../src/mock/stl';
import { unitAdvice } from '../../src/lib/units';
import { FIXTURE_DIR, toArrayBuffer } from './helpers';

describe('binary mesh format (contract §3)', () => {
  it('round-trips and rejects truncated / out-of-range data', () => {
    const m = { positions: Float32Array.from([0, 0, 0, 1, 0, 0, 0, 1, 0]), indices: Uint32Array.from([0, 1, 2]) };
    const d = decodeMesh(encodeMesh(m));
    expect([...d.positions]).toEqual([...m.positions]);
    expect([...d.indices]).toEqual([0, 1, 2]);
    expect(() => decodeMesh(encodeMesh(m).slice(0, 20))).toThrow(/truncated/);
    const bad = encodeMesh({ positions: m.positions, indices: Uint32Array.from([0, 1, 7]) });
    expect(() => decodeMesh(bad)).toThrow(/out of range/);
  });

  it('fixture meshes are in the canonical frame (AABB centred at the origin)', () => {
    const m = decodeMesh(toArrayBuffer(readFileSync(resolve(FIXTURE_DIR, 'meshes', 'p01.bin'))));
    const lo = [Infinity, Infinity, Infinity];
    const hi = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < m.positions.length; i += 3)
      for (let k = 0; k < 3; k++) {
        lo[k] = Math.min(lo[k], m.positions[i + k]);
        hi[k] = Math.max(hi[k], m.positions[i + k]);
      }
    for (let k = 0; k < 3; k++) expect(lo[k] + hi[k]).toBeCloseTo(0, 5);
    expect(hi[0] - lo[0]).toBeCloseTo(80, 4);
    expect(hi[2] - lo[2]).toBeCloseTo(22, 4);
  });
});

describe('mock STL reader', () => {
  it('parses binary STL, welds vertices and integrates a box exactly', () => {
    const buf = buildBinaryStl(boxTriangles([0, 0, 0], [80, 80, 22]));
    const m = parseStl(buf);
    expect(m.format).toBe('binary');
    expect(m.positions.length / 3).toBe(8);
    expect(checkMesh(m).boundaryEdges).toBe(0);
    const c = canonicalise(m, 1);
    expect(c.extents).toEqual([80, 80, 22]);
    const mp = massProps(c.positions64, c.indices);
    expect(mp.volume_mm3).toBeCloseTo(140800, 6);
    expect(mp.J_mm5[0][0]).toBeCloseTo(80772266.6667, 2);
  });

  it('parses ASCII STL', () => {
    const tris = boxTriangles([0, 0, 0], [1, 2, 3]);
    const txt = `solid t\n${tris.map((t) => `facet normal 0 0 0\nouter loop\n${t.map((v) => `vertex ${v.join(' ')}`).join('\n')}\nendloop\nendfacet`).join('\n')}\nendsolid t\n`;
    const m = parseStl(new TextEncoder().encode(txt).buffer as ArrayBuffer);
    expect(m.format).toBe('ascii');
    expect(massProps(canonicalise(m, 1).positions64, m.indices).volume_mm3).toBeCloseTo(6, 9);
  });

  it('finds the holes of an open mesh', () => {
    const tris = boxTriangles([0, 0, 0], [10, 10, 10]).slice(0, 10); // remove one face (2 triangles)
    const chk = checkMesh(parseStl(buildBinaryStl(tris)));
    expect(chk.boundaryEdges).toBe(4);
    expect(chk.boundaryLoops).toBe(1);
  });

  it('rejects garbage', () => {
    expect(() => parseStl(new TextEncoder().encode('not an stl at all').buffer as ArrayBuffer)).toThrow();
  });
});

describe('units advice for new STL files', () => {
  it('defaults to mm silently for CubeSat-sized parts', () => {
    expect(unitAdvice([80, 80, 22], 'mm')).toEqual({ suggest: null, warnings: [] });
  });
  it('warns that a tiny part looks like inches', () => {
    const a = unitAdvice([3.15, 3.15, 0.87], 'mm');
    expect(a.suggest).toBe('in');
    expect(a.warnings[0]).toMatch(/inches it is 80(\.0)? mm/);
  });
  it('warns that a very tiny part looks like metres', () => {
    const a = unitAdvice([0.08, 0.08, 0.022], 'mm');
    expect(a.suggest).toBe('m');
    expect(a.warnings[0]).toMatch(/metres it is 80(\.0)? mm/);
  });
  it('warns when the chosen unit makes the part too long for 3U', () => {
    expect(unitAdvice([80, 80, 22], 'cm').warnings.join(' ')).toMatch(/longer than the 340.5 mm/);
  });
});
