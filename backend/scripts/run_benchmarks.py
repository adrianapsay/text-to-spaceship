"""Run the protocol §J.3 benchmarks from the command line.

    uv run python scripts/run_benchmarks.py --budget 2000 --seeds 10 --workers 8 [--instances I1,I3] [--presets balanced]
Results go to data/runs/benchmarks/<UTC timestamp>/ (results.jsonl, benchmarks.json).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.bench.instances import dataset_instances  # noqa: E402
from t2s.bench.runner import PRESET_IDS, run_benchmarks  # noqa: E402
from t2s.parts.build import build_part  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def dataset_records():
    man = json.loads((REPO / "data" / "synthetic" / "manifest.json").read_text())
    recs = {}
    for p in man["parts"]:
        if p["role"] == "packable":
            recs[p["name"]] = build_part((REPO / "data" / "synthetic" / p["file"]).read_bytes(), p["name"], p["name"],
                                         file=p["file"])
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=2000)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--instances", default="I1,I2,I3,I4,I5")
    ap.add_argument("--presets", default=",".join(PRESET_IDS))
    ap.add_argument("--variants", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    t0 = time.perf_counter()
    recs = dataset_records()
    print(f"dataset built in {time.perf_counter() - t0:.0f}s", flush=True)
    want = set(a.instances.split(","))
    insts = [i for i in dataset_instances(recs) if i.id in want]
    out = Path(a.out) if a.out else REPO / "data" / "runs" / "benchmarks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    last = [0.0]

    def progress(frac, r):
        if frac - last[0] >= 0.02 or frac >= 1.0:
            last[0] = frac
            print(f"{100 * frac:5.1f} %  {r.get('instance')} {r.get('preset')} {r.get('variant')} seed {r.get('seed')} "
                  f"L={r.get('raw', {}).get('L', float('nan')):.1f} valid={r.get('valid')} {r.get('error', '')}", flush=True)
    s = run_benchmarks(insts, out, budget=a.budget, seeds=a.seeds, workers=a.workers,
                       presets=tuple(a.presets.split(",")), variants=tuple(a.variants.split(",")) if a.variants else None,
                       progress=progress)
    print(f"done in {s['seconds']:.0f}s -> {out}")
    print("validation:", s["validation"])
    print("adoption:", s["adoption"]["text"])
    for row in s["summary"]:
        print(f"  {row['instance']} {row['preset']:12s} {row['algorithm']:4s} median g {row['median_g']:.4f} "
              f"median L {row['median_L']:.1f} best L {row['best_L']:.1f} feasible {row['feasible']}/{row['n']}")


if __name__ == "__main__":
    main()
