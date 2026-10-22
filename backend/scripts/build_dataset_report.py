"""Build every dataset part through the pipeline and compare with the manifest's analytic values."""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.parts.build import build_part  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "data" / "synthetic"
man = json.loads((ROOT / "manifest.json").read_text())
rows = []
for i, p in enumerate(man["parts"]):
    data = (ROOT / p["file"]).read_bytes()
    t0 = time.perf_counter()
    rec = build_part(data, p["name"], f"p{i:02d}", file=p["file"])
    dt = time.perf_counter() - t0
    a = p.get("analytic")
    err = ""
    if a and rec.volume_mm3 is not None:
        r, o = rec.r_auth_to_can, rec.origin_auth
        com_a = (np.array(a["com_mm"]) - o) @ r
        j_a = r.T @ np.array(a["inertia_about_com_unit_density_mm5"]) @ r
        ev = abs(rec.volume_mm3 - a["volume_mm3"]) / a["volume_mm3"]
        ec = float(np.linalg.norm(rec.com_can_mm - com_a))
        ej = float(np.linalg.norm(rec.j_unit_mm5 - j_a) / np.linalg.norm(j_a))
        err = f"dV={ev:.1e} dC={ec:.1e} dJ={ej:.1e} [{a['basis'][:5]}]"
    ref = rec.ref_check
    rows.append((p["name"], rec.status, rec.frame_name, len(rec.allowed_orients), rec.boxes_method,
                 rec.boxes_certified, len(rec.cover.pieces), rec.cover.total_hull_volume or 0, rec.volume_mm3 or 0,
                 dt, err, ref.get("agree")))
    print(f"{p['name'][:26]:26s} {rec.status:9s} frame={rec.frame_name:12s} orients={len(rec.allowed_orients):2d} "
          f"G1={rec.boxes_method}:{len(rec.boxes)} cert={rec.boxes_certified} G3={len(rec.cover.pieces)}pc "
          f"over={(rec.cover.total_hull_volume / rec.volume_mm3 - 1) * 100 if rec.volume_mm3 else 0:6.2f}% "
          f"t={dt:5.2f}s ref={ref.get('agree')} {err}  {rec.status_detail[:60] if rec.status != 'VALID' else ''}",
          flush=True)
