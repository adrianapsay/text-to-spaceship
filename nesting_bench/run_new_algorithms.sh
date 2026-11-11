#!/bin/bash
# Benchmark runs for the five algorithms added 2026-11-10, same protocol as the large runs (datasets_large, n = 300 fast / 100 search, k = 10, 20, 30). Resumable.
cd "$(dirname "$0")"
for k in 10 20 30; do
  nice -n 5 python3 benchmark.py --algorithms skyline_3d wall_building --datasets_folder datasets_large --k $k --trials 300 --workers 1 --save_solutions --no_plot --name large_new_fast_k${k}_n300 --resume >> results/new_algorithms.log 2>&1
done
for k in 10 20 30; do
  nice -n 5 python3 benchmark.py --algorithms dblf_24 --datasets_folder datasets_large --k $k --trials 300 --workers 1 --save_solutions --no_plot --name large_new_dblf_k${k}_n300 --resume >> results/new_algorithms.log 2>&1
done
# beam_search / grasp_ems moved to run_search_algorithms.sh
echo ALL_DONE >> results/new_algorithms.log
