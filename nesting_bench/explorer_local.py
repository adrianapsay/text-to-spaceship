"""
Local Nesting Bench Explorer: the same page as the published artifact, built from whatever is in results/ on this machine, working offline.
    python explorer_local.py              rebuild explorer_local.html if any result or source changed, then open it in the browser
    python explorer_local.py --rebuild    rebuild even if nothing changed
    python explorer_local.py --no-open    rebuild only
On Windows, double-click OPEN_EXPLORER.bat.
"""
import os
import sys
import glob
import argparse
import subprocess
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "explorer_local.html")

parser = argparse.ArgumentParser()
parser.add_argument("--rebuild", action="store_true")
parser.add_argument("--no-open", action="store_true")
arguments = parser.parse_args()

# Everything the page is built from: summaries, saved packings, order study, algorithm cards, the page template, the animations and the build script.
inputs = []
for pattern in ["results/summary_large_*.csv", "results/verification_*_summary.csv", "results/verification_*_solutions.jsonl", "results/solutions_large_*_k10_n*.jsonl", "results/order_trials_*.csv", "results/order_solutions_*.jsonl", "results/order_solutions_*.jsonl.gz", "results/algorithm_cards/*", "explorer_template.html", "explorer_animations.js", "make_explorer.py", "vendor/three.r128.min.js"]:
    inputs.extend(glob.glob(os.path.join(HERE, pattern)))
newest_input = max(os.path.getmtime(path) for path in inputs)
stale = arguments.rebuild or not os.path.exists(PAGE) or os.path.getmtime(PAGE) < newest_input
if stale:
    print("Building explorer_local.html from results/ (about a minute) ...", flush=True)
    outcome = subprocess.run([sys.executable, os.path.join(HERE, "make_explorer.py"), "--offline", "--output", "explorer_local.html"], cwd=HERE)
    if outcome.returncode != 0:
        raise SystemExit("make_explorer.py failed; see the message above. It needs numpy, trimesh and scipy (pip install -r requirements.txt).")
else:
    print("explorer_local.html is up to date with results/.")
if not arguments.no_open:
    webbrowser.open("file:///" + PAGE.replace(os.sep, "/"))
    print("Opened " + PAGE)
