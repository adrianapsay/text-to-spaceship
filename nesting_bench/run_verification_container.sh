#!/bin/bash
# Scrabble container-mode verification for the five algorithms added 2026-11-10 (tag new5), split out so it can use the second core. Resumable.
cd "$(dirname "$0")/verification"
nice -n 10 python3 run_verification.py --test scrabble --mode container --algorithms skyline_3d wall_building dblf_24 beam_search grasp_ems --repeats 2 --workers 1 --tag new5 --resume >> ../results/verification_container.log 2>&1
echo ALL_DONE >> ../results/verification_container.log
