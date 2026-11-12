"""Parts imported 2026-11-11 from the pass 6 harvest (satcatalog / satsearch pages and the vendor data sheets behind them, downloaded on the lab laptop).
Each record was vetted: dimensions and mass read from the data sheet text next to a size word, mass agreeing with the catalog page, no duplicate of an existing part,
and the slug list in scratchpad p6_reject.txt removed by hand. Records live in harvest_2026_11_11.json."""
import os
import json

PARTS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harvest_2026_11_11.json"), encoding="utf-8"))
for record in PARTS:
    record.pop("harvest_slug", None)
