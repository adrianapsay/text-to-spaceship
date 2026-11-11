"""
Local Satellite Parts Catalog: the same page as the published artifact, built from the part folders on this machine, working offline.
    python catalog_local.py              rebuild catalog_local.html if catalog.csv, any part.json or the page sources changed, then open it in the browser
    python catalog_local.py --rebuild    rebuild even if nothing changed
    python catalog_local.py --no-open    rebuild only
On Windows, double-click OPEN_CATALOG.bat. After adding or changing parts in parts_data/, run generate_parts.py first (it rewrites catalog.csv and the part folders).
"""
import os
import sys
import glob
import argparse
import subprocess
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "catalog_local.html")

parser = argparse.ArgumentParser()
parser.add_argument("--rebuild", action="store_true")
parser.add_argument("--no-open", action="store_true")
arguments = parser.parse_args()

# Everything the page is built from: the catalog index, every part record, photos and datasheet pages, the page template and the build script.
inputs = [os.path.join(HERE, name) for name in ("catalog.csv", "catalog_explorer_template.html", "make_catalog_explorer.py", os.path.join("vendor", "three.r128.min.js"))]
for pattern in ["*/*/part.json", "*/*/reference_photo.jpg", "*/*/datasheet*_page1.png", "*/*/preview.png"]:
    inputs.extend(glob.glob(os.path.join(HERE, pattern)))
newest_input = max(os.path.getmtime(path) for path in inputs)
stale = arguments.rebuild or not os.path.exists(PAGE) or os.path.getmtime(PAGE) < newest_input
if stale:
    print("Building catalog_local.html from the part folders (about a minute) ...", flush=True)
    outcome = subprocess.run([sys.executable, os.path.join(HERE, "make_catalog_explorer.py"), "--offline", "--output", "catalog_local.html"], cwd=HERE)
    if outcome.returncode != 0:
        raise SystemExit("make_catalog_explorer.py failed; see the message above. It needs numpy, trimesh and pillow.")
else:
    print("catalog_local.html is up to date with the part folders.")
if not arguments.no_open:
    webbrowser.open("file:///" + PAGE.replace(os.sep, "/"))
    print("Opened " + PAGE)
