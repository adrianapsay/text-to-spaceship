import type { Mat3, Vec3 } from '../api/types';

export const ZERO3: Vec3 = [0, 0, 0];
export const IDENTITY3: Mat3 = [
  [1, 0, 0],
  [0, 1, 0],
  [0, 0, 1],
];

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const norm = (a: Vec3): number => Math.sqrt(dot(a, a));
export const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];

export function matVec(M: Mat3 | number[][], v: Vec3): Vec3 {
  return [
    M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2],
    M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2],
    M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2],
  ];
}

export function matMul(A: Mat3 | number[][], B: Mat3 | number[][]): Mat3 {
  const out: Mat3 = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[i][j] = A[i][0] * B[0][j] + A[i][1] * B[1][j] + A[i][2] * B[2][j];
  return out;
}

export function transpose(A: Mat3 | number[][]): Mat3 {
  return [
    [A[0][0], A[1][0], A[2][0]],
    [A[0][1], A[1][1], A[2][1]],
    [A[0][2], A[1][2], A[2][2]],
  ];
}

export function matAdd(A: Mat3, B: Mat3): Mat3 {
  return A.map((r, i) => r.map((v, j) => v + B[i][j])) as Mat3;
}

export function matScale(A: Mat3, s: number): Mat3 {
  return A.map((r) => r.map((v) => v * s)) as Mat3;
}

export function det3(M: Mat3 | number[][]): number {
  return (
    M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) -
    M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) +
    M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0])
  );
}

export const trace = (M: Mat3): number => M[0][0] + M[1][1] + M[2][2];

/** Normalise the wire rotation table (nested 3×3 or flat 9) into Mat3[]. */
export function normaliseRotations(table: number[][][] | number[][] | null | undefined): Mat3[] {
  if (!table) return [];
  return (table as unknown[]).map((m) => {
    const arr = m as number[] | number[][];
    if (Array.isArray(arr[0])) {
      const n = arr as number[][];
      return [
        [n[0][0], n[0][1], n[0][2]],
        [n[1][0], n[1][1], n[1][2]],
        [n[2][0], n[2][1], n[2][2]],
      ] as Mat3;
    }
    const f = arr as number[];
    return [
      [f[0], f[1], f[2]],
      [f[3], f[4], f[5]],
      [f[6], f[7], f[8]],
    ] as Mat3;
  });
}

/**
 * Jacobi eigen-decomposition of a symmetric 3×3 matrix.
 * Returns eigenvalues ascending and the matching unit eigenvectors as COLUMNS of `vectors`.
 */
export function eigSym3(Min: Mat3): { values: Vec3; vectors: Mat3 } {
  const A = Min.map((r) => r.slice()) as number[][];
  const V = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ];
  for (let sweep = 0; sweep < 64; sweep++) {
    const off = A[0][1] ** 2 + A[0][2] ** 2 + A[1][2] ** 2;
    const scaleRef = A[0][0] ** 2 + A[1][1] ** 2 + A[2][2] ** 2 + 1e-300;
    if (off <= 1e-30 * scaleRef) break;
    for (let p = 0; p < 2; p++)
      for (let q = p + 1; q < 3; q++) {
        const apq = A[p][q];
        if (Math.abs(apq) < 1e-300) continue;
        const theta = (A[q][q] - A[p][p]) / (2 * apq);
        const t = (theta >= 0 ? 1 : -1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1);
        const s = t * c;
        for (let k = 0; k < 3; k++) {
          const akp = A[k][p];
          const akq = A[k][q];
          A[k][p] = c * akp - s * akq;
          A[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < 3; k++) {
          const apk = A[p][k];
          const aqk = A[q][k];
          A[p][k] = c * apk - s * aqk;
          A[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < 3; k++) {
          const vkp = V[k][p];
          const vkq = V[k][q];
          V[k][p] = c * vkp - s * vkq;
          V[k][q] = s * vkp + c * vkq;
        }
      }
  }
  const order = [0, 1, 2].sort((i, j) => A[i][i] - A[j][j]);
  const values = order.map((i) => A[i][i]) as Vec3;
  const vectors = [0, 1, 2].map((r) => order.map((c) => V[r][c])) as Mat3;
  return { values, vectors };
}

const PERMS: [number, number, number][] = [
  [0, 1, 2],
  [0, 2, 1],
  [1, 0, 2],
  [1, 2, 0],
  [2, 0, 1],
  [2, 1, 0],
];

/**
 * Principal frame matched to the body axes (protocol §E.3): best of 6 permutations, each axis sign-fixed so its
 * matched component is positive, frame made right-handed; misalignment θ = arccos((tr(V) − 1)/2) in degrees.
 * Returns axes as ROWS (axes[k] = principal axis matched to body axis k) and the moment for each.
 */
export function matchPrincipalFrame(values: Vec3, vectors: Mat3): { axes: Mat3; moments: Vec3; tiltDeg: number; degenerate: boolean } {
  const cols: Vec3[] = [0, 1, 2].map((c) => [vectors[0][c], vectors[1][c], vectors[2][c]] as Vec3);
  let best = PERMS[0];
  let bestScore = -Infinity;
  for (const p of PERMS) {
    // p[k] = eigen-column assigned to body axis k
    const s = Math.abs(cols[p[0]][0]) + Math.abs(cols[p[1]][1]) + Math.abs(cols[p[2]][2]);
    if (s > bestScore + 1e-12) {
      bestScore = s;
      best = p;
    }
  }
  const axes = best.map((c, k) => {
    const v = cols[c];
    return (v[k] < 0 ? scale(v, -1) : v) as Vec3;
  }) as Mat3;
  const moments = best.map((c) => values[c]) as Vec3;
  if (det3(axes) < 0) {
    // flip the axis whose matched component is smallest
    let k = 0;
    for (let i = 1; i < 3; i++) if (Math.abs(axes[i][i]) < Math.abs(axes[k][k])) k = i;
    axes[k] = scale(axes[k], -1);
  }
  const tr = axes[0][0] + axes[1][1] + axes[2][2];
  const tiltDeg = (Math.acos(Math.max(-1, Math.min(1, (tr - 1) / 2))) * 180) / Math.PI;
  const sorted = [...values].sort((a, b) => a - b);
  const rel = (a: number, b: number) => Math.abs(b - a) / Math.max(Math.abs(b), 1e-300);
  const degenerate = rel(sorted[0], sorted[1]) < 1e-3 || rel(sorted[1], sorted[2]) < 1e-3;
  return { axes, moments, tiltDeg, degenerate };
}
