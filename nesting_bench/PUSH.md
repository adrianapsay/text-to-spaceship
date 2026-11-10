# Pushing this folder to the team repo (from your laptop)

The repo is adrianapsay/text-to-spaceship. Do this once, in a terminal, after unzipping nesting_bench.zip:

    cd "C:\Users\danie\Documents\Engineering Projects\text-to-spaceship"
    git pull
    git checkout -b dadmehr/nesting-bench
    (copy the unzipped nesting_bench folder into the repo root, replacing the old datasets folder: the datasets now live in nesting_bench\datasets)
    git rm -r --cached datasets  (only if the old datasets folder is still tracked at the root; then delete it)
    git add nesting_bench
    git commit -m "nesting_bench: 10 algorithms, interactive viewer, parallel benchmark, n = 1000 and k sweep results, slides"
    git push -u origin dadmehr/nesting-bench

Then open a pull request on GitHub for Adrian to review. CLAUDE.md inside the folder gives any Claude session the project context; copy it to the repo root too if the team wants it to apply to the whole repo.

The results folder is about 50 MB of CSVs. If the team prefers a small repo, add `nesting_bench/results/trials_*.csv` to .gitignore and keep only the summary CSVs, PNGs and slides.pdf.
