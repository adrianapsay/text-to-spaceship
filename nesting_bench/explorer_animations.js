// Algorithm sketches for the Algorithms tab: one 2D canvas animation per algorithm, drawn procedurally (no data needed).
// Each sketch is a function (ctx, t, W, H, rng) called every frame with t = seconds since the animation started; it loops on its own period.
// Shared helpers: a tiny 2D bottom-left packer that produces a plausible placement sequence for rectangles.

const ANIM = (() => {
  function mulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let x = a; x = Math.imul(x ^ (x >>> 15), x | 1); x ^= x + Math.imul(x ^ (x >>> 7), x | 61); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }
  const COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"];
  const INK = "#1b2129", RED = "#e34948", GREEN = "#2f7a4d", GREY = "#9aa3ad", LIGHT = "#e4e8ec";

  function parts(seed, count, scale) {
    const rng = mulberry(seed);
    const list = [];
    for (let i = 0; i < count; i++) list.push({ w: Math.round((0.6 + rng() * 2.4) * scale), h: Math.round((0.6 + rng() * 2.4) * scale), c: COLORS[i % COLORS.length] });
    return list;
  }
  function largestFirst(list) { return [...list].sort((a, b) => b.w * b.h - a.w * a.h); }
  // bottom-left packing in a strip of width floorW: candidate positions are corners of placed boxes.
  function packBottomLeft(list, floorW) {
    const placed = [];
    for (const p of list) {
      const cands = [[0, 0]];
      placed.forEach(q => { cands.push([q.x + q.w, q.y]); cands.push([q.x, q.y + q.h]); });
      let best = null;
      for (const [x, y] of cands) {
        if (x + p.w > floorW) continue;
        if (placed.some(q => x < q.x + q.w && q.x < x + p.w && y < q.y + q.h && q.y < y + p.h)) continue;
        if (!best || y < best[1] || (y === best[1] && x < best[0])) best = [x, y];
      }
      if (!best) best = [0, Math.max(0, ...placed.map(q => q.y + q.h))];
      placed.push({ ...p, x: best[0], y: best[1], cands: cands.filter(([x, y]) => x + p.w <= floorW) });
    }
    return placed;
  }
  function box(ctx, x, y, w, h, fill, stroke, alpha) {
    ctx.globalAlpha = alpha == null ? 1 : alpha;
    if (fill) { ctx.fillStyle = fill; ctx.fillRect(x, y, w, h); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1.2; ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1); }
    ctx.globalAlpha = 1;
  }
  function label(ctx, text, x, y, color, size, align) { ctx.fillStyle = color || INK; ctx.font = Math.min(size || 12, 11.5) + "px IBM Plex Sans, system-ui, sans-serif"; ctx.textAlign = align || "left"; ctx.fillText(text, x, y); }
  function ease(u) { return u < 0 ? 0 : u > 1 ? 1 : u * u * (3 - 2 * u); }
  // floor coordinates: origin bottom-left of a drawing area
  function floor(ctx, W, H, pad) { return { ox: pad, oy: H - pad, sx: (W - 2 * pad), sy: (H - 2 * pad) }; }
  function drawPlaced(ctx, f, placed, upto, unit) {
    placed.slice(0, upto).forEach(q => box(ctx, f.ox + q.x * unit, f.oy - (q.y + q.h) * unit, q.w * unit, q.h * unit, q.c, INK, 0.85));
  }
  function bboxOf(placed, upto) { let mx = 0, my = 0; placed.slice(0, upto).forEach(q => { mx = Math.max(mx, q.x + q.w); my = Math.max(my, q.y + q.h); }); return [mx, my]; }

  const S = {};

  // 1. random rejection: tries flash red when they hit, green when free
  S.random_rejection = (ctx, t, W, H) => {
    const rng = mulberry(7);
    const unit = 14, f = floor(ctx, W, H, 24), region = 14;
    box(ctx, f.ox, f.oy - region * unit, region * unit, region * unit, null, GREY);
    const list = parts(3, 8, 1.6).map(p => ({ ...p }));
    const placed = [];
    const triesPerPart = 12, tryTime = 0.09, period = list.length * triesPerPart * tryTime + 1.5;
    const tt = t % period;
    let clock = 0;
    for (let i = 0; i < list.length; i++) {
      const p = list[i];
      for (let k = 0; k < triesPerPart; k++) {
        const x = Math.floor(rng() * (region - p.w)), y = Math.floor(rng() * (region - p.h));
        const hit = placed.some(q => x < q.x + q.w + 0.5 && q.x < x + p.w + 0.5 && y < q.y + q.h + 0.5 && q.y < y + p.h + 0.5);
        const last = k === triesPerPart - 1;
        const accept = !hit || last;
        const start = clock; clock += tryTime;
        if (tt >= start && tt < start + tryTime) {
          drawPlaced(ctx, f, placed, placed.length, unit);
          box(ctx, f.ox + x * unit, f.oy - (y + p.h) * unit, p.w * unit, p.h * unit, accept ? GREEN : RED, INK, accept ? 0.9 : 0.5);
          label(ctx, accept ? "free: accepted" : "hits a placed box: rejected", f.ox, 18, accept ? GREEN : RED, 13);
          label(ctx, "part " + (i + 1) + " of " + list.length + " · try " + (k + 1), W - 24, 18, GREY, 12, "right");
          return;
        }
        if (accept) { placed.push({ ...p, x, y }); break; }
      }
    }
    drawPlaced(ctx, f, placed, placed.length, unit);
    label(ctx, "done: " + placed.length + " parts placed, lots of air", f.ox, 18, INK, 13);
  };

  // 2. shelf packing: rows fill left to right; wasted strip above shorter parts shaded
  S.shelf_packing = (ctx, t, W, H) => {
    const unit = 13, f = floor(ctx, W, H, 24), floorW = 20;
    const list = [...parts(11, 10, 1.6)].sort((a, b) => b.h - a.h);
    const placed = []; let x = 0, y = 0, rowH = 0;
    for (const p of list) { if (x + p.w > floorW) { x = 0; y += rowH; rowH = 0; } placed.push({ ...p, x, y, rowY: y }); x += p.w; rowH = Math.max(rowH, p.h); }
    const period = placed.length * 0.5 + 1.5, tt = t % period, upto = Math.min(placed.length, Math.floor(tt / 0.5) + 1);
    box(ctx, f.ox, f.oy - 16 * unit, floorW * unit, 16 * unit, null, GREY);
    const rows = {}; placed.slice(0, upto).forEach(q => { rows[q.rowY] = Math.max(rows[q.rowY] || 0, q.h); });
    placed.slice(0, upto).forEach(q => { const rh = rows[q.rowY]; if (rh > q.h) box(ctx, f.ox + q.x * unit, f.oy - (q.rowY + rh) * unit, q.w * unit, (rh - q.h) * unit, RED, null, 0.18); });
    drawPlaced(ctx, f, placed, upto, unit);
    Object.keys(rows).forEach(ry => { ctx.strokeStyle = GREY; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(f.ox, f.oy - (Number(ry) + rows[ry]) * unit); ctx.lineTo(f.ox + floorW * unit, f.oy - (Number(ry) + rows[ry]) * unit); ctx.stroke(); ctx.setLineDash([]); });
    label(ctx, "tallest first, fill the row, then the next row; red = wasted above shorter parts", f.ox, 18, INK, 12);
  };

  // 3. bottom-left: candidate dots at every placed edge, pick lowest then leftmost
  S.box_bottom_left = (ctx, t, W, H) => {
    const unit = 13, f = floor(ctx, W, H, 24), floorW = 20;
    const placed = packBottomLeft(largestFirst(parts(5, 9, 1.7)), floorW);
    const step = 0.9, period = placed.length * step + 1.5, tt = t % period, i = Math.min(placed.length - 1, Math.floor(tt / step)), u = (tt - i * step) / step;
    box(ctx, f.ox, f.oy - 16 * unit, floorW * unit, 16 * unit, null, GREY);
    drawPlaced(ctx, f, placed, i, unit);
    const p = placed[i];
    p.cands.forEach(([x, y]) => { ctx.fillStyle = GREY; ctx.beginPath(); ctx.arc(f.ox + x * unit, f.oy - y * unit, 3, 0, 7); ctx.fill(); });
    const sy = 15, cy = p.y + (sy - p.y) * (1 - ease(u * 1.6)), cx = p.x;
    box(ctx, f.ox + cx * unit, f.oy - (cy + p.h) * unit, p.w * unit, p.h * unit, p.c, INK, 0.85);
    ctx.fillStyle = "#eb6834"; ctx.beginPath(); ctx.arc(f.ox + p.x * unit, f.oy - p.y * unit, 5, 0, 7); ctx.fill();
    label(ctx, "grey dots = candidate corners; orange = lowest, then leftmost free one", f.ox, 18, INK, 12);
  };

  // 4. extreme points: only exposed corners; each candidate evaluated by the box it would make
  S.box_extreme_points = (ctx, t, W, H) => {
    const unit = 13, f = floor(ctx, W, H, 24), floorW = 22;
    const placed = packBottomLeft(largestFirst(parts(9, 8, 1.7)), floorW);
    const step = 1.3, period = placed.length * step + 1.5, tt = t % period, i = Math.min(placed.length - 1, Math.floor(tt / step)), u = (tt - i * step) / step;
    drawPlaced(ctx, f, placed, i, unit);
    const pts = [[0, 0]]; placed.slice(0, i).forEach(q => { pts.push([q.x + q.w, q.y]); pts.push([q.x, q.y + q.h]); });
    const p = placed[i];
    const k = Math.min(pts.length - 1, Math.floor(u * pts.length * 1.2));
    pts.forEach(([x, y], n) => { ctx.fillStyle = n === k ? "#eb6834" : GREY; ctx.beginPath(); ctx.arc(f.ox + x * unit, f.oy - y * unit, n === k ? 5 : 3, 0, 7); ctx.fill(); });
    const [cx, cy] = u < 0.85 ? pts[k] : [p.x, p.y];
    box(ctx, f.ox + cx * unit, f.oy - (cy + p.h) * unit, p.w * unit, p.h * unit, p.c, INK, u < 0.85 ? 0.45 : 0.85);
    const [mx, my] = bboxOf(placed, i); const bx = Math.max(mx, cx + p.w), by = Math.max(my, cy + p.h);
    box(ctx, f.ox, f.oy - by * unit, bx * unit, by * unit, null, u < 0.85 ? "#eb6834" : INK);
    label(ctx, "try each exposed corner; keep the one with the smallest overall box (" + (bx * by) + ")", f.ox, 18, INK, 12);
  };

  // 5. empty maximal spaces: free space as overlapping green boxes that split when a part lands
  S.empty_maximal_spaces = (ctx, t, W, H) => {
    const unit = 13, f = floor(ctx, W, H, 24), floorW = 22, floorH = 16;
    const placed = packBottomLeft(largestFirst(parts(21, 7, 1.8)), floorW);
    const step = 1.2, period = placed.length * step + 1.5, tt = t % period, i = Math.min(placed.length - 1, Math.floor(tt / step)), u = (tt - i * step) / step;
    let empties = [{ x: 0, y: 0, w: floorW, h: floorH }];
    const split = (p) => { const next = []; empties.forEach(e => { if (p.x >= e.x + e.w || p.x + p.w <= e.x || p.y >= e.y + e.h || p.y + p.h <= e.y) { next.push(e); return; } if (p.x > e.x) next.push({ x: e.x, y: e.y, w: p.x - e.x, h: e.h }); if (p.x + p.w < e.x + e.w) next.push({ x: p.x + p.w, y: e.y, w: e.x + e.w - p.x - p.w, h: e.h }); if (p.y > e.y) next.push({ x: e.x, y: e.y, w: e.w, h: p.y - e.y }); if (p.y + p.h < e.y + e.h) next.push({ x: e.x, y: p.y + p.h, w: e.w, h: e.y + e.h - p.y - p.h }); }); empties = next.filter(e => e.w >= 1 && e.h >= 1); };
    for (let n = 0; n < i; n++) split(placed[n]);
    if (u > 0.6) split(placed[i]);
    empties.forEach(e => box(ctx, f.ox + e.x * unit, f.oy - (e.y + e.h) * unit, e.w * unit, e.h * unit, "#1baf7a", "#1baf7a", 0.12));
    drawPlaced(ctx, f, placed, i, unit);
    const p = placed[i]; box(ctx, f.ox + p.x * unit, f.oy - (p.y + p.h) * unit, p.w * unit, p.h * unit, p.c, INK, u > 0.3 ? 0.85 : 0.3);
    label(ctx, "green = maximal empty boxes (" + empties.length + "); the part lands at a corner, the boxes it cuts split", f.ox, 18, INK, 12);
  };

  // 6. skyline: profile line; box rests on the highest column under it; waste in red
  S.skyline_3d = (ctx, t, W, H) => {
    const unit = 13, f = floor(ctx, W, H, 24), floorW = 22;
    const heights = new Array(floorW).fill(0);
    const list = largestFirst(parts(31, 9, 1.6));
    const placed = [];
    for (const p of list) { let best = null; for (let x = 0; x + p.w <= floorW; x++) { const base = Math.max(...heights.slice(x, x + p.w)); const waste = heights.slice(x, x + p.w).reduce((s, h) => s + base - h, 0); if (!best || base + p.h < best.top || (base + p.h === best.top && waste < best.waste)) best = { x, base, top: base + p.h, waste }; } placed.push({ ...p, x: best.x, y: best.base, waste: heights.slice(best.x, best.x + p.w).map(h => best.base - h) }); for (let x = best.x; x < best.x + p.w; x++) heights[x] = best.top; }
    const step = 0.9, period = placed.length * step + 1.5, tt = t % period, i = Math.min(placed.length - 1, Math.floor(tt / step)), u = (tt - i * step) / step;
    const hs = new Array(floorW).fill(0);
    placed.slice(0, i).forEach(q => { for (let x = q.x; x < q.x + q.w; x++) hs[x] = Math.max(hs[x], q.y + q.h); });
    drawPlaced(ctx, f, placed, i, unit);
    const p = placed[i];
    p.waste.forEach((w, n) => { if (w > 0) box(ctx, f.ox + (p.x + n) * unit, f.oy - p.y * unit, unit, w * unit, RED, null, 0.25); });
    ctx.strokeStyle = INK; ctx.lineWidth = 2.5; ctx.beginPath(); for (let x = 0; x < floorW; x++) { ctx.lineTo(f.ox + x * unit, f.oy - hs[x] * unit); ctx.lineTo(f.ox + (x + 1) * unit, f.oy - hs[x] * unit); } ctx.stroke(); ctx.lineWidth = 1;
    const cy = p.y + (14 - p.y) * (1 - ease(u * 1.5));
    box(ctx, f.ox + p.x * unit, f.oy - (cy + p.h) * unit, p.w * unit, p.h * unit, p.c, INK, 0.85);
    label(ctx, "the skyline (black) is the stack top; drop where the result is lowest, then least waste (red)", f.ox, 18, INK, 12);
  };

  // 7. wall building: vertical walls along x, each filled top to bottom
  S.wall_building = (ctx, t, W, H) => {
    const unit = 13, f = floor(ctx, W, H, 24), faceH = 16;
    const list = largestFirst(parts(41, 10, 1.6));
    const placed = []; let wallX = 0, wallW = 0, y = 0;
    const remaining = [...list];
    while (remaining.length) { wallW = remaining[0].w; y = 0; let any = false; for (let n = 0; n < remaining.length;) { const p = remaining[n]; if (p.w <= wallW && y + p.h <= faceH) { placed.push({ ...p, x: wallX, y, wallX, wallW }); y += p.h; remaining.splice(n, 1); any = true; } else n++; } if (!any) break; wallX += wallW; }
    const step = 0.55, period = placed.length * step + 1.5, tt = t % period, upto = Math.min(placed.length, Math.floor(tt / step) + 1);
    const walls = {}; placed.slice(0, upto).forEach(q => { walls[q.wallX] = q.wallW; });
    Object.keys(walls).forEach(wx => box(ctx, f.ox + Number(wx) * unit, f.oy - faceH * unit, walls[wx] * unit, faceH * unit, null, GREY));
    drawPlaced(ctx, f, placed, upto, unit);
    ctx.strokeStyle = INK; ctx.beginPath(); ctx.moveTo(f.ox, f.oy + 6); ctx.lineTo(f.ox + 22 * unit, f.oy + 6); ctx.stroke(); label(ctx, "walls along x", f.ox + 22 * unit + 6, f.oy + 10, GREY, 11);
    label(ctx, "the first part sets the wall's depth; the wall face fills; then the next wall", f.ox, 18, INK, 12);
  };

  // 8. force based: overlapping boxes pushed apart, squeezed toward the centroid
  S.force_based = (ctx, t, W, H) => {
    const rng = mulberry(5), unit = 12, cx = W / 2, cy = H / 2 + 10;
    const list = parts(8, 9, 1.6).map(p => ({ ...p, x: (rng() - 0.5) * 6, y: (rng() - 0.5) * 6 }));
    const period = 6, tt = t % period, iterations = Math.floor(tt / period * 40);
    for (let it = 0; it < iterations; it++) {
      list.forEach(p => { p.x *= 0.9; p.y *= 0.9; });
      for (let pass = 0; pass < 6; pass++) for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) { const p = list[a], q = list[b]; const ox = (p.w + q.w) / 2 + 0.3 - Math.abs(p.x - q.x), oy = (p.h + q.h) / 2 + 0.3 - Math.abs(p.y - q.y); if (ox > 0 && oy > 0) { if (ox < oy) { const s = Math.sign(p.x - q.x) || 1; p.x += s * ox / 2; q.x -= s * ox / 2; } else { const s = Math.sign(p.y - q.y) || 1; p.y += s * oy / 2; q.y -= s * oy / 2; } } }
    }
    list.forEach(p => box(ctx, cx + (p.x - p.w / 2) * unit, cy - (p.y + p.h / 2) * unit, p.w * unit, p.h * unit, p.c, INK, 0.6));
    ctx.fillStyle = INK; ctx.beginPath(); ctx.arc(cx, cy, 4, 0, 7); ctx.fill();
    label(ctx, "iteration " + iterations + " of 40: squeeze 10% toward the centroid, push overlapping pairs apart", 24, 18, INK, 12);
  };
  S.force_based_v2 = (ctx, t, W, H) => { S.force_based(ctx, t, W, H); const unit = 12, cx = W / 2, cy = H / 2 + 10; box(ctx, cx - 6 * unit, cy - 6 * unit, 12 * unit, 12 * unit, null, "#eb6834"); ctx.setLineDash([]); label(ctx, "v2: the squeeze is stronger along the axis that sticks out of the target cube (orange)", 24, H - 8, "#eb6834", 12); };

  // 9. voxel bottom-left: a grid, an L-shaped part, overlap counts per position, zero = free
  S.voxel_bottom_left = (ctx, t, W, H) => {
    const cell = 16, cols = 18, rows = 12, ox = 24, oy = H - 24;
    const grid = []; for (let y = 0; y < rows; y++) { grid.push([]); for (let x = 0; x < cols; x++) grid[y].push(0); }
    const stamp = (shape, px, py, v) => shape.forEach(([x, y]) => { if (grid[py + y]) grid[py + y][px + x] = v; });
    const L = [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [0, 2], [0, 3]], Tpiece = [[0, 0], [1, 0], [2, 0], [1, 1], [1, 2]], small = [[0, 0], [1, 0], [0, 1], [1, 1]];
    stamp(L, 0, 0, 1); stamp(Tpiece, 5, 0, 2); stamp([[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]], 9, 0, 3); stamp(small, 14, 0, 4);
    const period = 5, tt = t % period;
    const part = small;
    const free = []; for (let y = 0; y < rows - 1; y++) for (let x = 0; x < cols - 1; x++) { const hit = part.some(([dx, dy]) => grid[y + dy][x + dx] !== 0); free.push([x, y, hit]); }
    const scan = Math.floor(tt / period * free.length);
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) { const v = grid[y][x]; box(ctx, ox + x * cell, oy - (y + 1) * cell, cell, cell, v ? COLORS[v] : null, LIGHT, 0.8); }
    if (tt < 4) {
      for (let n = 0; n <= Math.min(scan, free.length - 1); n++) { const [x, y, hit] = free[n]; ctx.fillStyle = hit ? RED : GREEN; ctx.globalAlpha = 0.25; ctx.fillRect(ox + x * cell + 4, oy - (y + 1) * cell + 4, 8, 8); ctx.globalAlpha = 1; }
      label(ctx, "overlap count at every position at once (FFT): red = collides, green = free", 24, 18, INK, 12);
    } else {
      stamp(part, 1, 1, 5); for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) { if (grid[y][x] === 5) box(ctx, ox + x * cell, oy - (y + 1) * cell, cell, cell, "#eb6834", LIGHT, 0.9); }
      label(ctx, "keep the free spot that keeps the box smallest: it nests inside the L's notch", 24, 18, INK, 12);
    }
  };

  // 10. heightfield drop: column heights; the part's bottom profile lands on the stack's top profile
  S.heightfield_drop = (ctx, t, W, H) => {
    const unit = 13, f = floor(ctx, W, H, 24), cols = 22;
    const stack = [1, 1, 3, 3, 3, 2, 2, 4, 4, 1, 1, 1, 2, 2, 5, 5, 3, 3, 3, 1, 1, 1];
    const bottom = [0, 0, 1, 1, 0], top = [2, 2, 2, 2, 2];
    const period = 4, tt = t % period, u = ease(Math.min(1, tt / 2.2));
    const xs = [2, 6, 11, 14, 16]; const x0 = xs[Math.floor((t / period) % xs.length)];
    const landing = Math.max(...bottom.map((b, i) => stack[x0 + i] - b));
    stack.forEach((h, x) => box(ctx, f.ox + x * unit, f.oy - h * unit, unit, h * unit, "#4e79a7", "#fff", 0.8));
    const y = landing + (12 - landing) * (1 - u);
    bottom.forEach((b, i) => box(ctx, f.ox + (x0 + i) * unit, f.oy - (y + top[i]) * unit, unit, (top[i] - b) * unit, "#eb6834", "#fff", 0.9));
    ctx.strokeStyle = INK; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(f.ox + x0 * unit, f.oy - landing * unit - 1); ctx.lineTo(f.ox + (x0 + 5) * unit, f.oy - landing * unit - 1); ctx.stroke(); ctx.setLineDash([]);
    label(ctx, "landing height = max over columns of (stack top minus part bottom); tried at every x and orientation", f.ox, 18, INK, 12);
  };

  // 11. DBLF-24: the voxel idea with all 24 orientations cycled before the deepest position is taken
  S.dblf_24 = (ctx, t, W, H) => {
    const cx = W / 2, cy = H / 2 + 10, period = 6, tt = t % period;
    const n = Math.floor(tt / period * 24);
    const shape = [[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [0, 0, 1]];
    const angle = n * Math.PI / 12, tilt = (n % 4) * 0.5;
    const proj = ([x, y, z]) => { const rx = x * Math.cos(angle) - y * Math.sin(angle), ry = x * Math.sin(angle) + y * Math.cos(angle); return [cx + (rx - 1) * 26 + ry * 10 * Math.cos(tilt), cy - (z - 0.5) * 26 - ry * 12]; };
    shape.forEach(c => { const [px, py] = proj(c); box(ctx, px - 12, py - 12, 24, 24, "#1baf7a", INK, 0.8); });
    label(ctx, "orientation " + (n + 1) + " of 24", cx, cy + 70, INK, 14, "center");
    label(ctx, "every axis-aligned orientation is voxelized; the deepest, then lowest, then leftmost free cell wins", 24, 18, INK, 12);
  };

  // 12. best of fast: six packers race; the densest gets kept
  S.best_of_fast = (ctx, t, W, H) => {
    const names = ["shelf", "bottom-left", "extreme pts", "EMS", "voxel", "heightfield"], dens = [0.46, 0.55, 0.62, 0.64, 0.60, 0.58];
    const period = 5, tt = t % period, u = Math.min(1, tt / 3.2);
    names.forEach((name, i) => { const x = 40 + i * (W - 80) / 6, w = (W - 80) / 6 - 14; const h = dens[i] * 150 * ease(Math.min(1, u * 1.4 - i * 0.08)); box(ctx, x, H - 50 - h, w, h, i === 3 && u >= 1 ? "#eb6834" : "#4e79a7", INK, 0.85); label(ctx, name, x + w / 2, H - 32, INK, 11, "center"); if (u >= 1) label(ctx, dens[i].toFixed(2), x + w / 2, H - 56 - h, INK, 11, "center"); });
    label(ctx, u >= 1 ? "all six run on the same parts; keep the densest (EMS here)" : "running all six constructive packers...", 24, 18, INK, 12);
  };

  // 13. simulated annealing: a genome (order + orientation), one swap per step, accept if better or by chance; temperature falls
  S.simulated_annealing = (ctx, t, W, H) => {
    const rng = mulberry(13), n = 8, period = 9, tt = t % period, steps = 30, step = Math.floor(tt / period * steps);
    let order = [0, 1, 2, 3, 4, 5, 6, 7], ori = [0, 2, 1, 0, 3, 1, 2, 0], score = 0.40, history = [score];
    let lastSwap = null, lastAccepted = true;
    for (let s = 0; s < step; s++) { const a = Math.floor(rng() * n), b = Math.floor(rng() * n); const temp = 0.05 * Math.pow(0.02, s / steps); const gain = (rng() - 0.38) * 0.04; const accept = gain > 0 || rng() < Math.exp(gain / temp); lastSwap = [a, b]; lastAccepted = accept; if (accept) { [order[a], order[b]] = [order[b], order[a]]; score = Math.min(0.72, score + gain); } history.push(score); }
    order.forEach((id, i) => { const x = 30 + i * 46; box(ctx, x, 34, 40, 40, (lastSwap && (i === lastSwap[0] || i === lastSwap[1])) ? (lastAccepted ? GREEN : RED) : COLORS[id], INK, 0.85); label(ctx, String.fromCharCode(65 + id), x + 20, 60, "#fff", 16, "center"); label(ctx, "o" + ori[id], x + 20, 90, GREY, 11, "center"); });
    label(ctx, "genome: placement order + orientation per part; one swap per step", 30, 20, INK, 12);
    const gx = 30, gy = H - 30, gw = W - 60, gh = 80;
    ctx.strokeStyle = GREY; ctx.strokeRect(gx, gy - gh, gw, gh);
    ctx.strokeStyle = "#eb6834"; ctx.lineWidth = 2; ctx.beginPath(); history.forEach((v, i) => { const x = gx + i / steps * gw, y = gy - (v - 0.35) / 0.4 * gh; if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); }); ctx.stroke(); ctx.lineWidth = 1;
    const temp = 0.05 * Math.pow(0.02, step / steps);
    label(ctx, "density " + score.toFixed(3) + "   temperature " + temp.toFixed(4) + (lastSwap ? (lastAccepted ? "   accepted" : "   rejected (worse)") : ""), gx, gy - gh - 6, INK, 12);
  };

  // 14. genetic: population rows with fitness bars; keep the best half; crossover slice; mutation
  function genetic(ctx, t, W, H, decoderName) {
    const rng = mulberry(17), pop = 8, n = 8, period = 8, tt = t % period, phase = tt / period;
    let genomes = []; for (let g = 0; g < pop; g++) { const o = [0, 1, 2, 3, 4, 5, 6, 7].sort(() => rng() - 0.5); genomes.push({ o, fit: 0.35 + rng() * 0.3 }); }
    genomes.sort((a, b) => b.fit - a.fit);
    const gen = Math.floor(phase * 4), sub = (phase * 4) % 1;
    for (let g = 0; g < gen; g++) { const kept = genomes.slice(0, pop / 2); const children = kept.map((p, i) => { const q = kept[(i + 1) % kept.length]; const a = 2, b = 5; const slice = p.o.slice(a, b); const rest = q.o.filter(v => !slice.includes(v)); const o = rest.slice(0, a).concat(slice, rest.slice(a)); return { o, fit: Math.min(0.75, (p.fit + q.fit) / 2 + rng() * 0.08), child: true }; }); genomes = kept.map(k => ({ ...k, child: false })).concat(children).sort((a, b) => b.fit - a.fit); }
    genomes.forEach((g, r) => { const y = 36 + r * 28; const dead = sub > 0.35 && r >= pop / 2; g.o.forEach((id, i) => box(ctx, 30 + i * 22, y, 20, 20, dead ? LIGHT : (g.child && sub > 0.7 && i >= 2 && i < 5 ? "#eb6834" : COLORS[id]), INK, dead ? 0.4 : 0.85)); box(ctx, 220, y + 4, g.fit * 200, 12, dead ? LIGHT : "#4e79a7", null, 0.9); label(ctx, g.fit.toFixed(2), 428, y + 15, dead ? GREY : INK, 11); if (dead) label(ctx, "dropped", 470, y + 15, RED, 11); else if (g.child) label(ctx, "child", 470, y + 15, GREEN, 11); });
    label(ctx, "generation " + (gen + 1) + ": decode each genome with the " + decoderName + ", keep the best half, breed children by order crossover (orange slice) + one mutation", 30, 20, INK, 11);
  }
  S.genetic_algorithm = (ctx, t, W, H) => genetic(ctx, t, W, H, "voxel packer");
  S.genetic_heightfield = (ctx, t, W, H) => genetic(ctx, t, W, H, "heightfield drop (10x cheaper)");
  S.genetic_box = (ctx, t, W, H) => genetic(ctx, t, W, H, "exact box packer (50x cheaper)");

  // 15. beam search: tree levels; keep the best B nodes
  S.beam_search = (ctx, t, W, H) => {
    const rng = mulberry(23), B = 3, levels = 5, period = 7, tt = t % period, level = Math.min(levels - 1, Math.floor(tt / period * levels));
    let nodes = [{ x: W / 2, score: 0.5 }];
    const rows = [nodes];
    for (let l = 1; l <= level; l++) { const children = []; rows[l - 1].filter(n => n.kept !== false).forEach((p, i) => { for (let c = 0; c < 3; c++) children.push({ parent: p, score: Math.min(0.8, p.score + (rng() - 0.4) * 0.1) }); }); children.sort((a, b) => b.score - a.score); children.forEach((c, i) => { c.kept = i < B; }); const w = Math.min(60, (W - 60) / children.length); children.forEach((c, i) => { c.x = W / 2 + (i - (children.length - 1) / 2) * w; }); rows.push(children); }
    rows.forEach((row, l) => row.forEach(n => { const y = 40 + l * 42; if (n.parent) { ctx.strokeStyle = n.kept ? INK : LIGHT; ctx.beginPath(); ctx.moveTo(n.parent.x, y - 42 + 10); ctx.lineTo(n.x, y - 10); ctx.stroke(); } box(ctx, n.x - 14, y - 10, 28, 20, n.kept === false ? LIGHT : "#eb6834", INK, 0.9); if (n.kept !== false) label(ctx, n.score.toFixed(2), n.x, y + 4, "#fff", 9, "center"); }));
    label(ctx, "level " + (level + 1) + ": every kept packing is extended by every remaining part; keep the best " + B + " (orange)", 24, 18, INK, 12);
  };

  // 16. GRASP: repeated randomized EMS constructions; choice among the 3 best spots; best kept
  S.grasp_ems = (ctx, t, W, H) => {
    const unit = 10, period = 8, tt = t % period, runs = 6, run = Math.min(runs - 1, Math.floor(tt / period * runs));
    const results = [];
    for (let r = 0; r <= run; r++) { const rng = mulberry(100 + r); const list = largestFirst(parts(21, 7, 1.8)); for (let i = 0; i < list.length - 1; i++) if (rng() < 0.3) [list[i], list[i + 1]] = [list[i + 1], list[i]]; const placed = packBottomLeft(list, 14 + Math.floor(rng() * 4)); const [mx, my] = bboxOf(placed, placed.length); const area = placed.reduce((s, p) => s + p.w * p.h, 0); results.push({ placed, dens: area / (mx * my), mx, my }); }
    const best = results.reduce((a, b) => b.dens > a.dens ? b : a);
    results.forEach((res, r) => { const ox = 30 + r * (W - 40) / runs, oy = H - 40; res.placed.forEach(q => box(ctx, ox + q.x * unit * 0.45, oy - (q.y + q.h) * unit * 0.45, q.w * unit * 0.45, q.h * unit * 0.45, q.c, INK, res === best ? 0.95 : 0.5)); label(ctx, res.dens.toFixed(2) + (res === best ? " best" : ""), ox, oy + 16, res === best ? "#eb6834" : GREY, 11); });
    label(ctx, "construction " + (run + 1) + ": perturbed order + random pick among the 3 best spots; keep the densest", 24, 18, INK, 12);
  };

  return { sketches: S, has: name => Boolean(S[name]) };
})();
