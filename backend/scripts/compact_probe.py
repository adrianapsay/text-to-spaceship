"""M6 probe: certified drop compaction on constructive layouts (development check, not a benchmark)."""
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.collision.geom import part_geom_from_record  # noqa: E402
from t2s.collision.validate import StageSpec, Validator  # noqa: E402
from t2s.decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart  # noqa: E402
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, layout_metrics  # noqa: E402
from t2s.optimise.compact import compactor_from_records  # noqa: E402
from t2s.parts.build import build_part  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "data" / "synthetic"
cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if cache and cache.exists():
    recs = pickle.loads(cache.read_bytes())
else:
    man = json.loads((ROOT / "manifest.json").read_text())
    recs = {p["name"]: build_part((ROOT / p["file"]).read_bytes(), p["name"], p["name"], file=p["file"])
            for p in man["parts"] if p["role"] == "packable"}
ids = list(recs)
dec = BoxDecoder([ProxyPart(i, recs[i].boxes, recs[i].allowed_orients) for i in ids], ENCLOSURE_LO, ENCLOSURE_HI,
                 PLACEMENT_GAP_STAGE1)
spec = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)
geoms = {i: part_geom_from_record(recs[i]) for i in ids}
val = Validator(geoms)
comp = compactor_from_records(recs, spec)
for name, order in (("volume", np.argsort([-recs[i].volume_mm3 for i in ids])),
                    ("boxvol", np.argsort([-np.prod(recs[i].boxes[:, 3:] - recs[i].boxes[:, :3], axis=1).sum() for i in ids])),
                    ("mindim", np.argsort([-recs[i].obb_extents_mm.min() for i in ids]))):
    r = dec.best_fit_all_orientations(list(order))
    poses = [(p, o, np.round(t * 1000) / 1000) for p, o, t in r.poses]
    m0 = layout_metrics(recs, geoms, poses)
    t0 = time.perf_counter()
    dirs = [(0, 0, -1)] if len(sys.argv) < 3 else [(0, 0, -1), (-1, 0, 0), (0, -1, 0), (1, 0, 0), (0, 1, 0)]
    c = comp.compact(poses, directions=dirs, passes=4)
    dt = time.perf_counter() - t0
    rep = val.validate(c.poses, spec)
    m1 = layout_metrics(recs, geoms, c.poses)
    moved = sorted(((v, k) for k, v in c.moved_mm.items() if v > 0), reverse=True)[:5]
    print(f"{name:7s} L {m0['length_used_mm']:.2f} -> {m1['length_used_mm']:.2f} mm  compaction {dt:.2f}s "
          f"passes={c.passes} checks={c.checks} valid={rep.valid} levels={ {k: v for k, v in rep.levels.items() if v} } "
          f"top moves={[(k, round(v, 2)) for v, k in moved]}")
    if not rep.valid:
        print("   violations:", rep.violations[:5])
