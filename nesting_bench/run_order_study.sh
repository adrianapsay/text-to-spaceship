#!/bin/bash
# Keeps the order study running until it finishes (resumable after container restarts).
cd "$(dirname "$0")"
for attempt in $(seq 1 30); do
  python3 order_study.py --name k10_k20 --k 10 20 --sets 10 --random_orders 20 --random_orders_search 8 --workers 2 >> results/order_study_k10_k20.log 2>&1 && break
  sleep 20
done
