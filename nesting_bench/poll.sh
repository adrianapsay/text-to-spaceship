#!/bin/bash
# Status of the four queues (one line each); relaunches any that died.
cd "$(dirname "$0")"
bash ensure_running.sh
date +%H:%M
echo "order: $(tail -1 results/order_study_k10_k20.log | cut -c1-60)"
echo "dblf/new: $(grep -o 'k [0-9]*\|--k [0-9]*' results/new_algorithms.log | tail -1) $(tail -1 results/new_algorithms.log | cut -c1-80)"
echo "search: $(tail -1 results/search_algorithms.log | cut -c1-80)"
echo "verif: $(tail -1 results/verification_new.log | cut -c1-80)"
echo "verif container: $(tail -1 results/verification_container.log | cut -c1-80)"
ls results | grep -c "summary_large_new"; ls results | grep "verification.*new5.*summary" | tr '\n' ' '
