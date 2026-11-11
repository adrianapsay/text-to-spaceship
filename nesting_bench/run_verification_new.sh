#!/bin/bash
# Scrabble (open mode; container mode is in run_verification_container.sh) and literature verification tests for the five algorithms added 2026-11-10 (tag new5), same protocol as the original runs. Resumable.
cd "$(dirname "$0")/verification"
ALGOS="skyline_3d wall_building dblf_24 beam_search grasp_ems"
for mode in container open; do
  nice -n 10 python3 run_verification.py --test literature --mode $mode --algorithms $ALGOS --repeats 5 --workers 1 --tag new5 --resume >> ../results/verification_new.log 2>&1
done
for mode in container open; do
  nice -n 10 python3 run_verification.py --test literature --mode $mode --algorithms dblf_24 --repeats 5 --workers 1 --voxel_pitch 1 --tag new5 --resume >> ../results/verification_new.log 2>&1
done
for mode in open; do
  nice -n 10 python3 run_verification.py --test scrabble --mode $mode --algorithms $ALGOS --repeats 2 --workers 1 --tag new5 --resume >> ../results/verification_new.log 2>&1
done
echo ALL_DONE >> ../results/verification_new.log
