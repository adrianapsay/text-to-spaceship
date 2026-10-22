"""M3 check: constructive box-decoder layouts for the dataset, each passed through the exact validator."""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.collision.geom import part_geom_from_record  # noqa: E402
from t2s.collision.validate import StageSpec, Validator  # noqa: E402
from t2s.decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart  # noqa: E402
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, layout_metrics  # noqa: E402
from t2s.parts.build import build_part  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "data" / "synthetic"
man = json.loads((ROOT / "manifest.json").read_text())
records, geoms = {}, {}
for i, p in enumerate(man["parts"]):
    if p["role"] != "packable":
        continue
    rec = build_part((ROOT / p["file"]).read_bytes(), p["name"], p["name"], file=p["file"])
    records[p["name"]] = rec
    geoms[p["name"]] = part_geom_from_record(rec)
ids = list(records)
proxies = [ProxyPart(pid, records[pid].boxes, records[pid].allowed_orients) for pid in ids]
dec = BoxDecoder(proxies, ENCLOSURE_LO, ENCLOSURE_HI, PLACEMENT_GAP_STAGE1)
spec = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)
val = Validator(geoms)
vol = np.array([records[p].volume_mm3 for p in ids])
boxvol = np.array([np.prod(records[p].boxes[:, 3:] - records[p].boxes[:, :3], axis=1).sum() for p in ids])
maxdim = np.array([records[p].obb_extents_mm.max() for p in ids])
mindim = np.array([records[p].obb_extents_mm.min() for p in ids])
orders = {"volume_desc": np.argsort(-vol), "boxvol_desc": np.argsort(-boxvol), "maxdim_desc": np.argsort(-maxdim),
          "mindim_desc": np.argsort(-mindim)}
for name, order in orders.items():
    t0 = time.perf_counter()
    res = dec.best_fit_all_orientations(list(order))
    t1 = time.perf_counter()
    rep = val.validate(res.poses, spec)
    t2 = time.perf_counter()
    m = layout_metrics(records, geoms, res.poses, min_clearance=rep.min_clearance_mm)
    print(f"{name:12s} placed={len(res.poses):2d} unplaced={res.unplaced} L={m['length_used_mm']:.1f} mm "
          f"valid={rep.valid} levels={ {k: v for k, v in rep.levels.items() if v} } decode={1e3 * (t1 - t0):.0f} ms "
          f"validate={1e3 * (t2 - t1):.0f} ms COM={np.round(m.get('com_mm', [np.nan] * 3), 1).tolist()}")
rng = np.random.default_rng(1)
n = len(ids)
t0 = time.perf_counter()
best = None
for k in range(200):
    keys = rng.random(3 * n)
    order = list(np.argsort(keys[:n]))
    r = dec.decode(order, keys[n:2 * n], keys[2 * n:])
    if not r.unplaced and (best is None or r.length_top < best[0]):
        best = (r.length_top, r)
dt = time.perf_counter() - t0
print(f"random-key decodes: {1e3 * dt / 200:.1f} ms each; best L of 200 = {best[0]:.1f} mm" if best else "none feasible")
rep = val.validate(best[1].poses, spec)
print("best random layout valid:", rep.valid, rep.levels)
