#!/bin/bash
# Order study in phases (resumable): the original 12 ordered algorithms first, then the cheap new ones, then the expensive new ones.
cd "$(dirname "$0")"
run() {
  for attempt in $(seq 1 20); do
    nice -n 19 python3 order_study.py --name k10_k20 --k 10 20 --sets 10 --random_orders 20 --random_orders_search 8 --workers 2 --algorithms "$@" >> results/order_study_k10_k20.log 2>&1 && return 0
    sleep 20
  done
}
run random_rejection shelf_packing box_bottom_left box_extreme_points empty_maximal_spaces voxel_bottom_left heightfield_drop simulated_annealing genetic_algorithm genetic_heightfield best_of_fast genetic_box
echo PHASE1_DONE >> results/order_study_k10_k20.log
run skyline_3d wall_building
echo PHASE2_DONE >> results/order_study_k10_k20.log
run dblf_24
echo PHASE3_DONE >> results/order_study_k10_k20.log
run beam_search grasp_ems
echo ALL_DONE >> results/order_study_k10_k20.log
