"""Recommended minimum search time per CubeSat size (V2: the search runs until the user presses Pause).

PROVISIONAL — one run, one setting, one PC. The only measurement so far is the user's own 7.5 h search of project
"default" (2026-10-24, 00:04:08 – 07:33:19 UTC): Stage 2, 3U, part size 54 %, one search context (parts_sig
d9acc1360120c3ea, spec_sig 2a65c8de635bde35), searching without a pause longer than 105 s (the longest gap between
two archived layouts), sliders unchanged for the first 367 min. Read from its archive.jsonl with
best_length_trajectory() below (read-only): the best used length L of its VALIDATED layouts against the time since the
run's first layout (the search started at most 16 s earlier, after the previous context's last layout):

    minutes   3.3    7.4    13.9   29.8   35.1   98.8   179.7  291.0  318.0 (… 449.2, no further improvement)
    L (mm)    171.6  160.3  149.0  147.6  145.1  144.0  143.3  142.9  142.87

The recommendation is the time after which the best L stayed within 1 % of that run's best (142.868 mm): 98.8 min
(within 2 %: 35.1 min; within 0.5 %: 179.7 min). Used length, not the score g: g changes with every normaliser epoch.
The run has no evaluation counts, so the minimum is wall time on this PC. Milestone 3 of the plan replaces it with a
measured distribution (at least 10 seeds per setting plus a 3–6 h reference run, on an idle machine).
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from datetime import datetime

PROVISIONAL_NOTE = ("provisional, from one 7.5 h run at 3U 54 % on this PC; to be replaced by a measured "
                    "distribution")

CONVERGENCE: dict[str, dict] = {
    "3U": {
        "minimum_s": 5930.0,               # 98.8 min (98 min 50 s) after the run's first layout
        "rule": "best used length within 1 % of that run's best",
        "provisional": True,
        "note": "Search-based and " + PROVISIONAL_NOTE + " (Stage 2, part size 54 %): after 98.8 min of searching, "
                "the best used length was within 1 % of that run's best (142.87 mm, reached after 318 min).",
        "run": {"project": "default", "stage": 2, "form_factor": "3U", "part_scale_pct": 54,
                "parts_sig": "d9acc1360120c3ea", "spec_sig": "2a65c8de635bde35",
                "first_layout": "2026-10-24T00:04:08+00:00", "last_layout": "2026-10-24T07:33:19+00:00",
                "validated_layouts": 7165, "best_mm": 142.868, "best_at_s": 19081.0,
                "within_s": {"0.5%": 10782.0, "1%": 5930.0, "2%": 2106.0, "5%": 832.0}},
    },
    # 6U and 12U: not measured yet — nothing is recommended for them
}


def recommended_minimum(form_factor: str) -> dict | None:
    """{"minimum_s", "note", "provisional"} for a CubeSat size, or None where nothing has been measured yet."""
    c = CONVERGENCE.get(form_factor)
    if c is None:
        return None
    return {"minimum_s": c["minimum_s"], "note": c["note"], "provisional": c["provisional"]}


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


def best_length_trajectory(lines: Iterable[bytes | str], parts_sig: str, spec_sig: str,
                           stage: int = 2) -> list[tuple[float, float, str]]:
    """(seconds since the run's first layout, best used length so far in mm, layout id) at every improvement, from
    the lines of an archive.jsonl: the layouts of one search context (stage, parts and rule signatures), the last
    line of an id winning; only VALIDATED or FINAL layouts count for the length, every layout for the start time."""
    last: dict[str, tuple[float, str, float | None]] = {}
    for line in lines:
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("stage") != stage or d.get("parts_sig") != parts_sig or d.get("spec_sig") != spec_sig \
                or not d.get("created"):
            continue
        last[d["id"]] = (_ts(d["created"]), d.get("status"), (d.get("raw") or {}).get("L"))
    if not last:
        return []
    t0 = min(t for t, _, _ in last.values())
    out: list[tuple[float, float, str]] = []
    for t, lid, status, length in sorted((t, lid, st, L) for lid, (t, st, L) in last.items()):
        if status in ("VALIDATED", "FINAL") and length is not None and (not out or length < out[-1][1] - 1e-9):
            out.append((t - t0, float(length), lid))
    return out


def time_within(trajectory: list[tuple[float, float, str]], frac: float) -> float | None:
    """Seconds after which the best length stayed within frac (0.01 = 1 %) of the trajectory's final best."""
    if not trajectory:
        return None
    limit = trajectory[-1][1] * (1.0 + frac)
    return next(t for t, length, _ in trajectory if length <= limit + 1e-9)


def main(argv: list[str]) -> None:
    """python -m t2s.bench.convergence_table <archive.jsonl> <parts_sig> <spec_sig>: the trajectory and the times."""
    with open(argv[0], "rb") as fh:
        traj = best_length_trajectory(fh, argv[1], argv[2])
    for t, length, lid in traj:
        print(f"{t / 60:8.2f} min  {length:9.3f} mm  {lid}")
    for frac in (0.005, 0.01, 0.02, 0.05):
        w = time_within(traj, frac)
        print(f"within {100 * frac:g} % of the best: {w:.0f} s ({w / 60:.1f} min)" if w is not None else "no layouts")


if __name__ == "__main__":
    main(sys.argv[1:])
