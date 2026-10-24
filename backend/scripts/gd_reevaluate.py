"""Re-check every saved contest design with the current evaluation (gd.evaluate) without regenerating it.

    uv run python scripts/gd_reevaluate.py [--workers 1] [--threads 2] [--env gevs] [--src DIR] [--note "why"]
Each ladder rung's STL is evaluated again in its own process (a gmsh crash cannot spoil the others); its mass must
match the recorded one (the same solid). The STLs are read from --src (default: the folder of results.json; they
are gitignored, so a worktree reads them from the main checkout's folder, read-only). The ladder rule is applied
again under the launch environment --env (gd.environment; the first passing rung is the entrant's result); a ladder
whose new decision would need a rung that was never generated is reported, not guessed. Standings, winner and the
winner's mesh-refinement check are rebuilt, results.json is rewritten with the before → after of every design
(margins, governing check, bolts), and docs/V2-GD-CONTEST.md is regenerated.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("MKL_CBWR", "AUTO")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np

from t2s.gd.contest import VOL_LADDER, contest_markdown, criteria, problems, standings, winner

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "gd_contest"
MASS_TOL = 1e-5                # relative: the STL stores float32 vertices of the evaluated solid


def _stl_mesh(path: Path):
    from t2s.geometry.stl_io import read_stl_bytes
    tris, _ = read_stl_bytes(path.read_bytes())
    v, inv = np.unique(tris.reshape(-1, 3), axis=0, return_inverse=True)
    return v, inv.reshape(-1, 3)


def child(a):
    """One design in this process: --one <problem index> <stl> <generator> [--h_fea x] → JSON summary on stdout."""
    from t2s.gd.domain import GenResult
    from t2s.gd.evaluate import evaluate
    h = json.loads(Path(a.results).read_text(encoding="utf-8"))["problems"][a.pi]["voxel_mm"]
    dom = problems(h)[a.pi][0]
    ev = evaluate(dom, GenResult(None, 0.0, a.gen, mesh=_stl_mesh(Path(a.src) / a.stl)), threads=a.threads,
                  h_fea=a.h_fea * dom.h if a.h_fea else None, env=a.env)
    print("RESULT " + json.dumps(ev.summary(), default=float))


def run_child(a, pi, stl, gen, h_fea=None):
    cmd = [sys.executable, __file__, "--one", str(pi), stl, gen, "--threads", str(a.threads), "--env", a.env,
           "--src", str(a.src), "--results", str(a.results)]
    if h_fea:
        cmd += ["--h_fea", str(h_fea)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    line = next((x for x in p.stdout.splitlines() if x.startswith("RESULT ")), None)
    if line is None:
        return {"ok": False, "passed": False, "reason": f"evaluation process failed (exit {p.returncode}): "
                                                         f"{(p.stderr or p.stdout)[-300:]}"}
    return json.loads(line[7:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", nargs=3, metavar=("PI", "STL", "GEN"))
    ap.add_argument("--h_fea", type=float, default=None, help="(child) interior element size as a multiple of h")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--env", default="gevs", help="launch environment preset (gd.environment)")
    ap.add_argument("--results", default=str(OUT / "results.json"), help="contest results.json (read and rewritten)")
    ap.add_argument("--src", default="", help="folder of the contest STLs (read only; default: next to --results)")
    ap.add_argument("--note", default="", help="text for the report, or @file to read it from a file")
    ap.add_argument("--cache", default="", help="folder for the per-design evaluations (<stl>.json), reused if present")
    ap.add_argument("--doc", default=str(REPO / "docs" / "V2-GD-CONTEST.md"))
    a = ap.parse_args()
    a.src = Path(a.src) if a.src else Path(a.results).parent
    if a.one:
        a.pi, a.stl, a.gen = int(a.one[0]), a.one[1], a.one[2]
        return child(a)
    if a.note.startswith("@"):
        a.note = Path(a.note[1:]).read_text(encoding="utf-8").strip()
    t0 = time.perf_counter()

    def log(msg):
        print(f"[{time.perf_counter() - t0:6.0f} s] {msg}", flush=True)
    res = json.loads(Path(a.results).read_text(encoding="utf-8"))
    pidx = {p["name"]: i for i, p in enumerate(res["problems"])}
    jobs = []                                  # (row index, attempt index, problem index, stl, generator)
    for ri, r in enumerate(res["rows"]):
        for ai, at in enumerate(r.get("attempts") or []):
            if at.get("mass_g") is not None:
                stl = f"{r['key']}_{r['problem'].split()[0]}_vf{at['vol_frac']}.stl"
                jobs.append((ri, ai, pidx[r["problem"]], stl, r["generator"]))
    missing = [j[3] for j in jobs if not (a.src / j[3]).is_file()]
    if missing:
        raise SystemExit(f"{len(missing)} STL files missing in {a.src}: {missing[:5]} …")
    log(f"{len(jobs)} saved designs, {a.workers} at a time, environment {a.env}, STLs from {a.src}")

    cache = Path(a.cache) if a.cache else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)

    def evaluated(name, pi, stl, gen, h_fea=None):
        hit = cache / f"{name}.json" if cache else None
        if hit and hit.exists():                 # FE results reused; margins scored again with the current rule
            from t2s.gd.domain import MATERIAL
            from t2s.gd.evaluate import score
            out = json.loads(hit.read_text(encoding="utf-8"))
            out.update(score(out["solvers"], MATERIAL, a.env))
            return out
        out = run_child(a, pi, stl, gen, h_fea=h_fea)
        if hit and out.get("ok"):
            hit.write_text(json.dumps(out, default=float), encoding="utf-8")
        return out

    def go(j):
        out = evaluated(j[3], j[2], j[3], j[4])
        log(f"{j[3]}: f1 {out.get('f1_hz')}, MS {out.get('ms_yield')} / {out.get('ms_ult')} / bolt "
            f"{out.get('ms_bolt')}, governing {out.get('governing')}, passed {out.get('passed')} {out.get('reason') or ''}")
        return j, out
    with ThreadPoolExecutor(a.workers) as ex:
        done = list(ex.map(go, jobs))
    new = {(j[0], j[1]): (j[3], out) for j, out in done}

    changes, ladder_notes, rows = [], [], []
    for ri, r in enumerate(res["rows"]):
        atts, best, stop = [], None, False
        for ai, at in enumerate(r.get("attempts") or []):
            if stop:
                ladder_notes.append(f"{r['generator']} on {r['problem']}: rung {at['vol_frac']} is no longer needed "
                                    "(a lighter rung passes now); kept in the ladder table")
                atts.append({**at, "result": at["result"] + " (no longer needed)"})
                continue
            if (ri, ai) not in new:
                atts.append(at)                # generator or meshing failure: nothing saved to re-check
                if best is None:
                    best = {k: v for k, v in r.items() if k != "attempts"} if not r.get("ok") else None
                continue
            stl, ev = new[(ri, ai)]
            if ev.get("mass_g") is None or abs(ev["mass_g"] - at["mass_g"]) > MASS_TOL * at["mass_g"]:
                raise SystemExit(f"{stl}: mass {ev.get('mass_g')} g does not match the recorded {at['mass_g']} g — "
                                 "the STL is not the evaluated solid; regenerate instead")
            old = r if r.get("vol_frac") == at["vol_frac"] else None
            row = {**{k: r[k] for k in ("problem", "generator", "key", "iterations", "notes") if k in r},
                   **ev, "vol_frac": at["vol_frac"], "stl": stl,
                   "gen_seconds": (old or {}).get("gen_seconds", r.get("gen_seconds"))}
            changes.append({"design": stl, "mass_g": ev["mass_g"],
                            "f1_old": at.get("f1_hz"), "f1_new": ev.get("f1_hz"),
                            "mode": ((ev.get("modes") or [{}])[0]).get("motion"),
                            "axis_f_old": [x["f_hz"] for x in (old or {}).get("axes", [])] or [None] * 3,
                            "axis_f_new": [x["f_hz"] for x in ev.get("axes", [])],
                            "ms_yield_old": (old or {}).get("ms_yield"), "ms_yield_new": ev.get("ms_yield"),
                            "ms_ult_old": (old or {}).get("ms_ult"), "ms_ult_new": ev.get("ms_ult"),
                            "ms_bolt": ev.get("ms_bolt"), "governing": ev.get("governing"),
                            "margins": ev.get("margins"),
                            "random": [{"axis": "xyz"[k], "cqc_3sigma_g": x.get("random_3sigma_g"),
                                        "cqc_qual_3sigma_g": x.get("random_qual_3sigma_g"),
                                        "miles_3sigma_g": x.get("random_miles_g"), "eff_mass_sum": x.get("eff_mass_sum"),
                                        "sigma3_limit_mpa": x.get("sigma3_limit_mpa"),
                                        "sigma3_qual_mpa": x.get("sigma3_qual_mpa")}
                                       for k, x in enumerate(ev.get("axes") or [])],
                            "flags": [f["code"] for f in ev.get("flags") or []],
                            "passed_old": at["passed"], "passed_new": ev.get("passed"), "reason_new": ev.get("reason")})
            atts.append({"vol_frac": at["vol_frac"], "mass_g": ev["mass_g"], "sigma_mpa": ev.get("sigma_mpa"),
                         "f1_hz": ev.get("f1_hz"), "passed": ev.get("passed"),
                         "result": "PASS" if ev.get("passed") else (ev.get("reason") or "FAIL")})
            if best is None or (row["passed"] and not best.get("passed")) or \
                    (not best.get("passed") and (row.get("ms_yield") or -9) > (best.get("ms_yield") or -9)):
                best = row
            if row["passed"]:
                stop = True
        if best is None:
            best = {k: v for k, v in r.items() if k != "attempts"}
        last = (r.get("attempts") or [{}])[-1].get("vol_frac")
        if not best.get("passed") and last is not None and last != VOL_LADDER[-1]:
            ladder_notes.append(f"{r['generator']} on {r['problem']}: no saved rung passes now and the ladder stopped at "
                                f"{last} — the next rungs were never generated (needs a contest re-run)")
        best["attempts"] = atts
        rows.append(best)

    old_winner = (res.get("winner") or {}).get("key")
    res["rows"], res["criteria"] = rows, criteria(a.env)
    res["standings"] = standings(rows, res["entrants"])
    res["winner"] = winner(res["standings"])
    if res["winner"]:                          # the winner's refinement check, again in separate processes
        conv = []
        for p in res["problems"]:
            r = next((x for x in rows if x.get("key") == res["winner"]["key"] and x["problem"] == p["name"]), None)
            if not r or not r.get("ok") or not r.get("stl"):
                continue
            fine = evaluated(f"refine_{r['stl']}", pidx[p["name"]], r["stl"], r["generator"], h_fea=0.75)
            conv.append({"problem": p["name"],
                         "note": "surface triangles split in four, interior element size 0.75 h (separate process)",
                         "reason": fine.get("reason"), "sigma_peak_mpa": [r.get("sigma_peak_mpa"), fine.get("sigma_peak_mpa")],
                         "sigma_mpa": [r["sigma_mpa"], fine.get("sigma_mpa")], "f1_hz": [r["f1_hz"], fine.get("f1_hz")],
                         "n_nodes": [r.get("n_nodes"), fine.get("n_nodes")],
                         "sigma_change": (fine["sigma_mpa"] - r["sigma_mpa"]) / r["sigma_mpa"] if fine.get("sigma_mpa") else None,
                         "f1_change": (fine["f1_hz"] - r["f1_hz"]) / r["f1_hz"] if fine.get("f1_hz") else None,
                         "passed_fine": bool(fine.get("passed")), "ms_yield": [r.get("ms_yield"), fine.get("ms_yield")],
                         "ms_ult": [r.get("ms_ult"), fine.get("ms_ult")], "ms_bolt": [r.get("ms_bolt"), fine.get("ms_bolt")],
                         "governing": fine.get("governing")})
            log(f"refinement {p['name']}: σ {r['sigma_mpa']:.1f} → {fine.get('sigma_mpa')}, f1 {r['f1_hz']:.0f} → "
                f"{fine.get('f1_hz')}, passed {fine.get('passed')}")
        res["winner"]["refinement"] = conv
    from t2s.gd import environment as envs
    E = envs.get(a.env)
    res["reevaluation"] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "changes": changes,
                           "ladder": ladder_notes, "environment": E.id, "environment_name": E.name,
                           "winner_before": old_winner, "winner_after": (res["winner"] or {}).get("key"),
                           "note": (a.note or f"Every saved design was evaluated again under {E.name} "
                                    "(scripts/gd_reevaluate.py; same solids, masses matched).")}
    Path(a.results).write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    if a.doc:
        Path(a.doc).write_text(contest_markdown(res), encoding="utf-8")
    log(f"done: winner {res['winner'] and res['winner']['why']} (before: {old_winner})")
    for s in res["standings"]:
        log(f"  {s['rank']}. {s['generator']}: passed {s['passed']}/{s['problems']}, total {s['total_mass_g']:.1f} g")
    for x in ladder_notes:
        log("  ladder: " + x)


if __name__ == "__main__":
    main()
