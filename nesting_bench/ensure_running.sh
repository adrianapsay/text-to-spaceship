#!/bin/bash
# Relaunches the two queues if they are not running (the container restarts now and then). Repairs truncated last lines first.
cd "$(dirname "$0")"
python3 - <<'PY'
import json, csv
lines = open("results/order_solutions_k10_k20.jsonl").read().split("\n")
if lines and lines[-1] == "": lines = lines[:-1]
try:
    json.loads(lines[-1])
except Exception:
    lines = lines[:-1]
    open("results/order_solutions_k10_k20.jsonl", "w").write("\n".join(lines) + "\n")
rows = list(csv.reader(open("results/order_trials_k10_k20.csv")))
if len(rows[-1]) != len(rows[0]):
    rows = rows[:-1]
if len(rows) - 1 > len(lines):
    rows = rows[:1 + len(lines)]
csv.writer(open("results/order_trials_k10_k20.csv", "w", newline="")).writerows(rows)
PY
if ! pgrep -f order_study.py > /dev/null && ! grep -q ALL_DONE results/order_study_k10_k20.log; then
  nohup ./run_order_study.sh > /dev/null 2>&1 &
  echo "relaunched order study"
fi
if ! pgrep -f "run_search_algorithms.sh" > /dev/null && ! grep -q ALL_DONE results/search_algorithms.log 2>/dev/null; then
  nohup ./run_search_algorithms.sh > /dev/null 2>&1 &
  echo "relaunched search algorithms"
fi
if ! pgrep -f "run_new_algorithms.sh" > /dev/null && ! grep -q ALL_DONE results/new_algorithms.log; then
  nohup ./run_new_algorithms.sh > /dev/null 2>&1 &
  echo "relaunched new algorithms"
fi
