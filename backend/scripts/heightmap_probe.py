"""M6 probe: height-map decoder vs box decoder (constructive orders), validity and timing (development check)."""
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.collision.geom import part_geom_from_record  # noqa: E402
from t2s.collision.validate import StageSpec, Validator  # noqa: E402
from t2s.decoders.heightmap import HeightmapDecoder  # noqa: E402
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, layout_metrics  # noqa: E402

recs = pickle.loads(Path(sys.argv[1]).read_bytes())
ids = list(recs)
n = len(ids)
spec = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)
geoms = {i: part_geom_from_record(recs[i]) for i in ids}
val = Validator(geoms)
orders = {"volume": np.argsort([-recs[i].volume_mm3 for i in ids]),
          "boxvol": np.argsort([-np.prod(recs[i].boxes[:, 3:] - recs[i].boxes[:, :3], axis=1).sum() for i in ids]),
          "maxdim": np.argsort([-recs[i].obb_extents_mm.max() for i in ids]),
          "mindim": np.argsort([-recs[i].obb_extents_mm.min() for i in ids])}
for h in [float(x) for x in (sys.argv[2:] or ["2", "1"])]:
    t0 = time.perf_counter()
    dec = HeightmapDecoder({i: (recs[i].v, recs[i].f, recs[i].allowed_orients) for i in ids}, ENCLOSURE_LO,
                           ENCLOSURE_HI, h=h)
    tb = time.perf_counter() - t0
    print(f"h={h} mm: footprints built in {tb:.2f}s (incl. JIT)")
    for name, order in orders.items():
        t0 = time.perf_counter()
        r = dec.best_fit_all_orientations(list(order))
        t1 = time.perf_counter()
        rep = val.validate(r.poses, spec)
        m = layout_metrics(recs, geoms, r.poses)
        print(f"  {name:7s} placed={len(r.poses)} unplaced={r.unplaced} L={m['length_used_mm']:.1f} "
              f"constructive {1e3 * (t1 - t0):.0f} ms valid={rep.valid} {rep.violations[:2]}")
    rng = np.random.default_rng(0)
    t0 = time.perf_counter()
    best = None
    for _ in range(50):
        k = rng.random(3 * n)
        r = dec.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
        if not r.unplaced and (best is None or r.length_top < best[0]):
            best = (r.length_top, r)
    dt = (time.perf_counter() - t0) / 50
    if best:
        rep = val.validate(best[1].poses, spec)
        print(f"  random decode {1e3 * dt:.1f} ms each; best of 50 L={best[0]:.1f} valid={rep.valid}")
