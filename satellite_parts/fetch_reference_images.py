"""
Downloads the supplier photo and datasheet for every part listed in references.csv (run this on a machine with normal web access):
    python fetch_reference_images.py            (skips files that already exist)
    python fetch_reference_images.py --force
Writes <category>/<id>/reference_photo.<ext>, <category>/<id>/datasheet.pdf and <category>/<id>/datasheet_page1.png, then rebuilds catalog_images.html.
Needs: pip install requests pymupdf
"""
import os
import csv
import sys
import time
import argparse
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
parser = argparse.ArgumentParser()
parser.add_argument("--force", action="store_true")
parser.add_argument("--only", nargs="*", default=None, help="category names")
arguments = parser.parse_args()
headers = {"User-Agent": "Mozilla/5.0 (satellite_parts library fetcher; academic use)"}


def download(url, path):
    if os.path.exists(path) and not arguments.force:
        return "exists"
    try:
        response = requests.get(url, headers=headers, timeout=60)
    except Exception as error:
        return "error " + str(error)[:80]
    if response.status_code != 200:
        return "http " + str(response.status_code)
    open(path, "wb").write(response.content)
    return "ok " + str(len(response.content) // 1024) + " kB"


def render_first_page(pdf_path, png_path):
    try:
        import fitz
    except ImportError:
        return "pymupdf missing"
    try:
        document = fitz.open(pdf_path)
        page = document[0]
        pixmap = page.get_pixmap(dpi=90)
        pixmap.save(png_path)
        return "rendered"
    except Exception as error:
        return "render error " + str(error)[:80]


rows = list(csv.DictReader(open(os.path.join(HERE, "references.csv"))))
for row in rows:
    if arguments.only and row["category"] not in arguments.only:
        continue
    folder = os.path.join(HERE, row["category"], row["part_id"])
    if not os.path.isdir(folder):
        continue
    messages = []
    if row["photo_url"]:
        extension = os.path.splitext(row["photo_url"].split("?")[0])[1].lower() or ".jpg"
        messages.append("photo " + download(row["photo_url"], os.path.join(folder, "reference_photo" + extension)))
    if row["datasheet_url"]:
        pdf_path = os.path.join(folder, "datasheet.pdf")
        messages.append("datasheet " + download(row["datasheet_url"], pdf_path))
        if os.path.exists(pdf_path):
            png_path = os.path.join(folder, "datasheet_page1.png")
            if not os.path.exists(png_path) or arguments.force:
                messages.append(render_first_page(pdf_path, png_path))
    if messages:
        print(row["part_id"].ljust(40) + "; ".join(messages), flush=True)
        time.sleep(0.3)
os.system(sys.executable + " " + os.path.join(HERE, "make_catalog_page.py"))
