"""
Pass 8: second download round on the pass 6 index (no new crawling).
    python harvest_more.py
1. For every pass 6 product that has a datasheet PDF but no photo: saves the largest picture on page 1-2 of the PDF as photo.jpg
   (satcatalog pages carry no product image, so this is where their photo comes from).
2. Downloads datasheet + product image for the satsearch products pass 6 did not reach (it stopped at 1200 downloads), up to MAX_DOWNLOADS.
3. Writes pass8_light.zip with the folders touched in this run (texts, page PNGs, photos; no PDFs). Send that zip back to Claude.
Safe to re-run. Takes about 30 to 60 minutes.
"""
import os
import io
import csv
import sys
import time
import zipfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
for module_name, package_name in (("requests", "requests"), ("pymupdf", "pymupdf"), ("PIL", "pillow")):
    try:
        __import__(module_name)
    except ImportError:
        subprocess.call([sys.executable, "-m", "pip", "install", "--quiet", package_name])
import requests
import pymupdf as fitz
import urllib3
from PIL import Image
urllib3.disable_warnings()

MAX_DOWNLOADS = 2500
MAX_MINUTES = 100
started = time.time()
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
out_root = os.path.join(HERE, "pass6")
log = open(os.path.join(HERE, "pass8_log.txt"), "a", encoding="utf-8")
touched = set()


def say(message):
    print(message, flush=True)
    log.write(time.strftime("%H:%M:%S ") + message + "\n")
    log.flush()


def minutes():
    return (time.time() - started) / 60.0


def get(url, timeout=40):
    for attempt in range(3):
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True, verify=attempt < 2)
            if response.status_code == 200:
                return response.content
            if response.status_code in (403, 404, 410):
                return None
        except Exception:
            pass
        time.sleep(1.0 + attempt)
    return None


def save_photo(image, path):
    if image.width < 200 or image.height < 200:
        return False
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    else:
        image = image.convert("RGB")
    image.thumbnail((800, 800))
    image.save(path, "JPEG", quality=85)
    return True


def largest_picture_in_pdf(pdf_path):
    try:
        document = fitz.open(pdf_path)
    except Exception:
        return None
    best = None
    best_area = 0
    for page_number in range(min(2, len(document))):
        for info in document[page_number].get_images(full=True):
            try:
                extracted = document.extract_image(info[0])
                image = Image.open(io.BytesIO(extracted["image"]))
                image.load()
            except Exception:
                continue
            area = image.width * image.height
            ratio = image.width / float(image.height)
            if area > best_area and 0.3 < ratio < 3.5:
                best = image
                best_area = area
    return best


# 1. photos from datasheet PDFs
folders = [os.path.join(out_root, name) for name in os.listdir(out_root) if os.path.isdir(os.path.join(out_root, name))]
made = 0
for folder in folders:
    pdf_path = os.path.join(folder, "datasheet.pdf")
    photo_path = os.path.join(folder, "photo.jpg")
    if os.path.exists(pdf_path) and not os.path.exists(photo_path) and not os.path.exists(os.path.join(folder, "photo_from_pdf_failed.txt")):
        picture = largest_picture_in_pdf(pdf_path)
        if picture is not None and save_photo(picture, photo_path):
            open(os.path.join(folder, "photo_source.txt"), "w", encoding="utf-8").write("largest picture on page 1-2 of datasheet.pdf\n")
            made = made + 1
            touched.add(folder)
        else:
            open(os.path.join(folder, "photo_from_pdf_failed.txt"), "w", encoding="utf-8").write("no picture of at least 200 px on page 1-2\n")
say("step 1: " + str(made) + " photos taken from datasheet PDFs")

# 2. downloads for products pass 6 did not reach (satsearch first: their pages carry a product image)
index = list(csv.DictReader(open(os.path.join(HERE, "pass6_index.csv"), encoding="utf-8")))
known = set()
if os.path.exists(os.path.join(HERE, "known_models.txt")):
    known = set(line.strip().lower() for line in open(os.path.join(HERE, "known_models.txt"), encoding="utf-8") if line.strip())
todo = [row for row in index if row.get("datasheet") and not os.path.exists(os.path.join(out_root, row["slug"], "datasheet.txt"))]
todo.sort(key=lambda row: (0 if row["source"] == "satsearch" and row.get("image") else 1))
say("step 2: " + str(len(todo)) + " products with a datasheet not downloaded yet")
downloaded = 0
for row in todo[:MAX_DOWNLOADS]:
    if minutes() > MAX_MINUTES:
        say("time limit reached")
        break
    folder = os.path.join(out_root, row["slug"])
    os.makedirs(folder, exist_ok=True)
    pdf_path = os.path.join(folder, "datasheet.pdf")
    if not os.path.exists(pdf_path):
        content = get(row["datasheet"], timeout=60)
        if content and content[:4] == b"%PDF":
            open(pdf_path, "wb").write(content)
    if os.path.exists(pdf_path) and not os.path.exists(os.path.join(folder, "datasheet.txt")):
        try:
            document = fitz.open(pdf_path)
            text = ""
            for page_number in range(min(10, len(document))):
                text = text + document[page_number].get_text() + "\n"
            open(os.path.join(folder, "datasheet.txt"), "w", encoding="utf-8").write(text[:150000])
            document[0].get_pixmap(dpi=60).save(os.path.join(folder, "datasheet_page1.png"))
        except Exception:
            pass
    photo_path = os.path.join(folder, "photo.jpg")
    if row.get("image") and not os.path.exists(photo_path):
        content = get(row["image"])
        if content:
            try:
                image = Image.open(io.BytesIO(content))
                image.load()
                save_photo(image, photo_path)
            except Exception:
                pass
    if os.path.exists(pdf_path) and not os.path.exists(photo_path):
        picture = largest_picture_in_pdf(pdf_path)
        if picture is not None and save_photo(picture, photo_path):
            open(os.path.join(folder, "photo_source.txt"), "w", encoding="utf-8").write("largest picture on page 1-2 of datasheet.pdf\n")
    open(os.path.join(folder, "source.txt"), "w", encoding="utf-8").write("page: " + row["url"] + "\ndatasheet: " + row.get("datasheet", "") + "\nimage: " + row.get("image", "") + "\nfetched by harvest_more.py on " + time.strftime("%Y-%m-%d") + "\n")
    touched.add(folder)
    downloaded = downloaded + 1
    if downloaded % 50 == 0:
        say("downloaded " + str(downloaded) + "/" + str(min(len(todo), MAX_DOWNLOADS)) + "  (" + str(int(minutes())) + " min)")
    time.sleep(0.2)

# 3. pack
zip_path = os.path.join(HERE, "pass8_light.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(os.path.join(HERE, "pass6_index.csv"), "pass6_index.csv")
    archive.write(os.path.join(HERE, "pass8_log.txt"), "pass8_log.txt")
    for folder in sorted(touched):
        for name in os.listdir(folder):
            if name.endswith((".txt", ".png", ".jpg")):
                full = os.path.join(folder, name)
                archive.write(full, os.path.relpath(full, HERE))
    for name in os.listdir(out_root):
        if name.startswith("_page__"):
            archive.write(os.path.join(out_root, name), os.path.join("pass6", name))
say("done: " + zip_path + "  (" + str(downloaded) + " downloads, " + str(made) + " photos from PDFs)")
