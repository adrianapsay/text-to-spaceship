"""Run the V2 generative-design contest (metal-AM brackets; every design checked with CalculiX and NGSolve).

    uv run python scripts/gd_contest.py [--h 1.0] [--budget 240] [--threads 2] [--entrants baseline,pymoto,...]
Results go to data/gd_contest/ (results.json, one STL per design); the app's Mounting Hardware tab shows them and
the bracket design job uses the winner.
"""
import argparse
import os
import sys
import time
from pathlib import Path

# MKL's conditional numerical reproducibility before any entrant loads MKL (pytopo3d stays bitwise repeatable
# with 2 threads only when it is set first)
os.environ.setdefault("MKL_CBWR", "AUTO")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.gd.contest import ENTRANTS, contest_markdown, run_contest

REPO = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h", type=float, default=1.0, help="voxel size (mm)")
    ap.add_argument("--budget", type=float, default=240.0, help="seconds per generator run")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--entrants", default=",".join(ENTRANTS))
    ap.add_argument("--out", default=str(REPO / "data" / "gd_contest"))
    ap.add_argument("--doc", default=str(REPO / "docs" / "V2-GD-CONTEST.md"), help="report path ('' = none)")
    a = ap.parse_args()
    t0 = time.perf_counter()

    def log(msg):
        print(f"[{time.perf_counter() - t0:7.0f} s] {msg}", flush=True)
    res = run_contest(a.out, h=a.h, budget_s=a.budget, threads=a.threads, entrants=a.entrants.split(","), log=log)
    if a.doc:
        Path(a.doc).write_text(contest_markdown(res), encoding="utf-8")
    log(f"done: winner {res['winner']}")
    for s in res["standings"]:
        log(f"  {s['rank']}. {s['generator']}: passed {s['passed']}/{s['problems']}, total {s['total_mass_g']:.1f} g")


if __name__ == "__main__":
    main()
