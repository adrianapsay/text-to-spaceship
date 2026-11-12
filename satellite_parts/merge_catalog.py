"""Merges catalog.csv after a partial run (generate_parts.py --only ...) back into the full catalog saved before the run.
    python merge_catalog.py <saved full catalog.csv>"""
import csv
import sys

backup = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
current = list(csv.DictReader(open("catalog.csv", encoding="utf-8")))
by_id = {row["id"]: row for row in backup}
for row in current:
    by_id[row["id"]] = row
with open("catalog.csv", "w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(current[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(sorted(by_id.values(), key=lambda row: (row["category"], row["id"])))
print(str(len(by_id)) + " parts in catalog.csv")
