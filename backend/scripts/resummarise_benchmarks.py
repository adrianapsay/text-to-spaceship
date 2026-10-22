"""Recompute benchmarks.json from a finished run's results.jsonl (no new runs): statistics and selector evidence."""
import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from t2s.bench.runner import summarise  # noqa: E402

folder = Path(sys.argv[1])
instances = pickle.loads((folder / "instances.pkl").read_bytes())
results = [json.loads(line) for line in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
old = json.loads((folder / "benchmarks.json").read_text(encoding="utf-8"))
meta = {k: old[k] for k in ("budget", "seeds", "jobs", "workers", "started", "seconds") if k in old}
s = summarise(results, instances, meta)
(folder / "benchmarks.json").write_text(json.dumps(s, indent=1, default=float), encoding="utf-8")
print("evidence rows:", len(s["evidence"]), "algorithms:", sorted({e["algorithm"] for e in s["evidence"]}))
