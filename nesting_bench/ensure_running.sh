#!/bin/bash
# Relaunches the queues if they are not running (the container restarts now and then). Repairs truncated last lines first.
cd "$(dirname "$0")"
if ! pgrep -f order_study.py > /dev/null; then
python3 - <<'PY'
# Safe repair: only cut an unfinished last line (a crash mid-write), in place, never rewrite the whole file (a killed rewrite once truncated the trials CSV).
import os
for path in ("results/order_solutions_k10_k20.jsonl", "results/order_trials_k10_k20.csv"):
    if not os.path.exists(path):
        continue
    with open(path, "rb+") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size == 0:
            continue
        back = min(size, 4_000_000)
        handle.seek(size - back)
        tail = handle.read(back)
        if not tail.endswith(b"\n"):
            handle.truncate(size - back + tail.rfind(b"\n") + 1)
PY
fi
if ! pgrep -f order_study.py > /dev/null && ! grep -q ALL_DONE results/order_study_k10_k20.log; then
  nohup ./run_order_study.sh > /dev/null 2>&1 &
  echo "relaunched order study"
fi
if ! pgrep -f "run_search_algorithms.sh" > /dev/null && ! grep -q ALL_DONE results/search_algorithms.log 2>/dev/null; then
  nohup ./run_search_algorithms.sh > /dev/null 2>&1 &
  echo "relaunched search algorithms"
fi
# PAUSE_DBLF_K30: dblf_24 at k = 30 (300 trials) cannot finish before the deadline because the container restarts often; paused 2026-11-11 so the order study and verification get the cores. Delete the file to resume.
if [ ! -f PAUSE_DBLF_K30 ] && ! pgrep -f "run_new_algorithms.sh" > /dev/null && ! grep -q ALL_DONE results/new_algorithms.log; then
  nohup ./run_new_algorithms.sh > /dev/null 2>&1 &
  echo "relaunched new algorithms"
fi
if ! pgrep -f "run_verification_new.sh" > /dev/null && ! grep -q ALL_DONE results/verification_new.log 2>/dev/null; then
  nohup ./run_verification_new.sh > /dev/null 2>&1 &
  echo "relaunched verification for new algorithms"
fi
if ! pgrep -f "run_verification_container.sh" > /dev/null && ! grep -q ALL_DONE results/verification_container.log 2>/dev/null; then
  nohup ./run_verification_container.sh > /dev/null 2>&1 &
  echo "relaunched container verification"
fi
