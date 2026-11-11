#!/bin/bash
# Search-method runs for beam_search and grasp_ems (n = 100, k = 10, 20, 30), split from run_new_algorithms.sh so it can run on the second core. Resumable.
cd "$(dirname "$0")"
for k in 10 20 30; do
  nice -n 5 python3 benchmark.py --algorithms beam_search grasp_ems --datasets_folder datasets_large --k $k --trials 100 --workers 1 --save_solutions --no_plot --name large_new_search_k${k}_n100 --resume >> results/search_algorithms.log 2>&1
done
echo ALL_DONE >> results/search_algorithms.log
