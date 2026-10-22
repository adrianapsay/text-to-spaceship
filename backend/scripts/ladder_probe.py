"""M6 probe: run the detail ladder for one part of the dataset and print the table (development check)."""
import json
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.fidelity.ladder import run_ladder  # noqa: E402
from t2s.optimise.scalarize import PRESETS  # noqa: E402

recs = pickle.loads(Path(sys.argv[1]).read_bytes())
pid = sys.argv[2]
out = Path(sys.argv[3])
t0 = time.perf_counter()
res = run_ladder(recs, pid, PRESETS["balanced"], out, budget_s=float(sys.argv[4]) if len(sys.argv) > 4 else 600)
print(f"{pid}: {time.perf_counter() - t0:.1f}s stop={res['stop_reason']} {res['stop_reasons']}")
for e in res["levels"]:
    row = f"  {e['level']:6s} overhead={e['overhead']:.3f} build={e['build_s']:.2f}s q={e['eval_us_median']}"
    for a, r in e["results"].items():
        if "skipped" in r:
            row += f" | {a}: skipped ({r['skipped']})"
        else:
            row += (f" | {a}: L={r['length_used_mm']:.1f} g={r['score_g']:.4f} fr={r['false_reject_rate']} "
                    f"gen={r['generation_s']:.2f}s valid={r['valid']}")
    print(row)
print("chosen:", json.dumps(res["chosen"]))
for a, why in res["reasons"].items():
    print(" ", a, "->", why)
