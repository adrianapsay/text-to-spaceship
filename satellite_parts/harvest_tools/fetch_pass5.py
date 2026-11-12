"""
Pass 5: photos and datasheets for the catalog parts that still miss them (list in pass5.csv, URLs found by Claude on 2026-11-11).

    python fetch_pass5.py

What it does:
1. Moves the datasheet PDFs that were found to be the wrong document (rejected_pass5.csv) into photos\\_rejected\\ so they are not used again.
2. For each part needing a datasheet: downloads direct PDFs, or harvests PDF links from product pages (satsearch, vendor, distributor).
   A PDF is kept only if its first 3 pages mention the part (must_terms). Up to 2 per part, saved as datasheet_p5_N.pdf with
   a page 1 PNG, a source txt and the full extracted text.
3. For each part needing a photo: direct image URL, or the og:image of a product page, or ("datasheet") the largest picture
   inside the part's datasheet PDF. Saved as reference_photo_p5.jpg (max 800 px) with photo_p5_source.txt.
4. Writes pass5_light.zip (no PDFs, a few MB) next to this script. Send that zip back to Claude.
Safe to re-run. Takes about 15 to 30 minutes.
"""
import os
import re
import io
import sys
import csv
import time
import shutil
import zipfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
for module_name, package_name in (("requests", "requests"), ("fitz", "pymupdf"), ("PIL", "pillow")):
    try:
        __import__(module_name)
    except ImportError:
        subprocess.call([sys.executable, "-m", "pip", "install", "--quiet", package_name])
import requests
import fitz
import urllib3
from PIL import Image
urllib3.disable_warnings()

TARGET_DATASHEETS = 2
MIN_PHOTO_SIDE = 200
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
photos_root = os.path.join(HERE, "photos")
rows = list(csv.DictReader(open(os.path.join(HERE, "pass5.csv"), encoding="utf-8")))
log_file = open(os.path.join(HERE, "pass5_log.csv"), "w", newline="", encoding="utf-8")
log_writer = csv.writer(log_file)
log_writer.writerow(["part_id", "kind", "url", "status"])
cache = {}


def host_of(url):
    match = re.match(r"https?://([^/]+)", url)
    if not match:
        return ""
    return match.group(1).lower().replace("www.", "")


def fetch(url, timeout=60):
    if url in cache:
        return cache[url]
    result = (None, "", "error")
    for verify in (True, False):
        try:
            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, verify=verify)
            if response.status_code == 200:
                result = (response.content, response.headers.get("content-type", ""), "ok")
            else:
                result = (None, "", "http " + str(response.status_code))
            break
        except Exception as error:
            result = (None, "", "error " + str(error)[:60])
    cache[url] = result
    return result


def absolute_link(link, base_url):
    link = link.replace("&amp;", "&").strip()
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return re.match(r"https?://[^/]+", base_url).group(0) + link
    if not link.startswith("http"):
        return base_url.rsplit("/", 1)[0] + "/" + link
    return link


def pdf_links_in(html, base_url):
    links = re.findall(r'(?:href|src|data-href|data-url)=["\']([^"\']+)["\']', html, flags=re.I)
    scored = []
    for link in links:
        low = link.lower()
        if not (".pdf" in low or "/datasheets/" in low or "datasheet" in low or "download" in low and "pdf" in low):
            continue
        link = absolute_link(link, base_url)
        score = 2 if any(word in low for word in ("datasheet", "data-sheet", "data_sheet", "spec", "catalog", "brochure", "technical", "flyer")) else 1
        scored.append((score, link))
    scored.sort(key=lambda item: -item[0])
    unique = []
    for score, link in scored:
        if link not in unique:
            unique.append(link)
    return unique[:8]


def page_image_links(html, base_url):
    found = []
    for pattern in (r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']'):
        for link in re.findall(pattern, html, flags=re.I):
            found.append(absolute_link(link, base_url))
    for link in re.findall(r'<img[^>]+(?:src|data-src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', html, flags=re.I):
        low = link.lower()
        if any(word in low for word in ("logo", "icon", "sprite", "flag", "avatar", "banner", "payment")):
            continue
        if any(word in low for word in ("product", "featured", "satcatalog", "upload", "media", "image")):
            found.append(absolute_link(link, base_url))
    unique = []
    for link in found:
        if link not in unique:
            unique.append(link)
    return unique[:6]


def pdf_text(pdf_path, pages):
    try:
        document = fitz.open(pdf_path)
        text = ""
        for page_number in range(min(pages, len(document))):
            text = text + document[page_number].get_text() + "\n"
        return text
    except Exception:
        return ""


def pdf_mentions(pdf_path, terms):
    text = re.sub(r"\s+", " ", pdf_text(pdf_path, 3).lower())
    if not terms:
        return True
    for term in terms:
        if term.strip() and term.strip().lower() in text:
            return True
    return False


def save_photo(image_bytes, folder, url, method):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception:
        return False
    if image.width < MIN_PHOTO_SIDE or image.height < MIN_PHOTO_SIDE:
        return False
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    else:
        image = image.convert("RGB")
    image.thumbnail((800, 800))
    image.save(os.path.join(folder, "reference_photo_p5.jpg"), "JPEG", quality=85)
    note = "url: " + url + "\nmethod: " + method + "\nfound by Claude (web search) on 2026-11-11; downloaded by fetch_pass5.py\n"
    open(os.path.join(folder, "photo_p5_source.txt"), "w", encoding="utf-8").write(note)
    return True


def largest_pdf_picture(pdf_path):
    best = None
    best_area = 0
    try:
        document = fitz.open(pdf_path)
        for page_number in range(min(2, len(document))):
            for image_info in document[page_number].get_images(full=True):
                try:
                    extracted = document.extract_image(image_info[0])
                except Exception:
                    continue
                area = extracted["width"] * extracted["height"]
                if area > best_area and extracted["width"] >= MIN_PHOTO_SIDE and extracted["height"] >= MIN_PHOTO_SIDE:
                    best_area = area
                    best = extracted["image"]
    except Exception:
        return None
    return best


# 1. move the rejected PDFs out of the part folders
rejected_folder = os.path.join(photos_root, "_rejected")
os.makedirs(rejected_folder, exist_ok=True)
moved = 0
for row in csv.DictReader(open(os.path.join(HERE, "rejected_pass5.csv"), encoding="utf-8")):
    folder = os.path.join(photos_root, row["category"], row["part_id"])
    for suffix in (".pdf", "_page1.png", "_source.txt"):
        path = os.path.join(folder, row["stem"] + suffix)
        if os.path.exists(path):
            shutil.move(path, os.path.join(rejected_folder, row["part_id"] + "__" + row["stem"] + suffix))
            if suffix == ".pdf":
                moved = moved + 1
print("moved " + str(moved) + " rejected PDFs to photos\\_rejected", flush=True)

# 2 and 3. datasheets, then photos
for row_number, row in enumerate(rows):
    folder = os.path.join(photos_root, row["category"], row["part_id"])
    os.makedirs(folder, exist_ok=True)
    terms = [term for term in row["must_terms"].split("|") if term.strip()]
    messages = []
    kept_pdfs = sorted(os.path.join(folder, name) for name in os.listdir(folder) if re.match(r"datasheet_p5_\d+\.pdf$", name))
    if row["need_datasheet"] == "yes":
        have = len(kept_pdfs)
        domains = set()
        for url in [item.strip() for item in row["datasheet_urls"].split("|") if item.strip()]:
            if have >= TARGET_DATASHEETS:
                break
            content, content_type, status = fetch(url)
            if content is None:
                messages.append(host_of(url) + " " + status)
                log_writer.writerow([row["part_id"], "datasheet page", url, status])
                continue
            if content[:4] == b"%PDF":
                candidates = [url]
            else:
                candidates = pdf_links_in(content.decode("utf-8", "ignore"), url)
            for candidate in candidates:
                if host_of(candidate) in domains:
                    continue
                pdf_content, pdf_type, pdf_status = fetch(candidate)
                if pdf_content is None or pdf_content[:4] != b"%PDF":
                    continue
                number = have + 1
                pdf_path = os.path.join(folder, "datasheet_p5_" + str(number) + ".pdf")
                open(pdf_path, "wb").write(pdf_content)
                if not pdf_mentions(pdf_path, terms):
                    os.remove(pdf_path)
                    log_writer.writerow([row["part_id"], "rejected", candidate, "does not mention " + row["must_terms"][:60]])
                    continue
                try:
                    fitz.open(pdf_path)[0].get_pixmap(dpi=60).save(os.path.join(folder, "datasheet_p5_" + str(number) + "_page1.png"))
                except Exception:
                    os.remove(pdf_path)
                    continue
                open(os.path.join(folder, "datasheet_p5_" + str(number) + "_source.txt"), "w", encoding="utf-8").write("url: " + candidate + "\nfound from: " + url + "\nfound by Claude (web search) on 2026-11-11; downloaded by fetch_pass5.py\n")
                open(os.path.join(folder, "datasheet_p5_" + str(number) + ".txt"), "w", encoding="utf-8").write(pdf_text(pdf_path, 40)[:300000])
                log_writer.writerow([row["part_id"], "datasheet_p5_" + str(number), candidate, "ok"])
                kept_pdfs.append(pdf_path)
                domains.add(host_of(candidate))
                have = have + 1
                messages.append("pdf " + host_of(candidate))
                break
            time.sleep(0.3)
    if row["need_photo"] == "yes" and os.path.exists(os.path.join(folder, "reference_photo_p5.jpg")):
        shutil.move(os.path.join(folder, "reference_photo_p5.jpg"), os.path.join(rejected_folder, row["part_id"] + "__reference_photo_p5.jpg"))
    if row["need_photo"] == "yes":
        got_photo = False
        for url in [item.strip() for item in row["photo_urls"].split("|") if item.strip()]:
            if got_photo:
                break
            if url == "datasheet":
                pdf_candidates = kept_pdfs + sorted(os.path.join(folder, name) for name in os.listdir(folder) if re.match(r"datasheet(_\d+)?\.pdf$", name))
                for pdf_path in pdf_candidates:
                    picture = largest_pdf_picture(pdf_path)
                    if picture and save_photo(picture, folder, os.path.basename(pdf_path), "largest picture on page 1-2 of the datasheet"):
                        got_photo = True
                        messages.append("photo from " + os.path.basename(pdf_path))
                        break
                continue
            content, content_type, status = fetch(url)
            if content is None:
                log_writer.writerow([row["part_id"], "photo", url, status])
                continue
            if "image" in content_type.lower() or content[:3] == b"\xff\xd8\xff" or content[:8] == b"\x89PNG\r\n\x1a\n":
                if save_photo(content, folder, url, "direct image"):
                    got_photo = True
                    messages.append("photo " + host_of(url))
                continue
            for image_url in page_image_links(content.decode("utf-8", "ignore"), url):
                image_content, image_type, image_status = fetch(image_url)
                if image_content is not None and save_photo(image_content, folder, image_url, "image on page " + url):
                    got_photo = True
                    messages.append("photo " + host_of(image_url))
                    break
        if not got_photo:
            messages.append("NO PHOTO")
    log_file.flush()
    print(str(row_number + 1) + "/" + str(len(rows)) + "  " + row["part_id"].ljust(40) + "; ".join(messages)[:110], flush=True)

log_file.close()
zip_path = os.path.join(HERE, "pass5_light.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(os.path.join(HERE, "pass5_log.csv"), "pass5_log.csv")
    for row in rows:
        folder = os.path.join(photos_root, row["category"], row["part_id"])
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.startswith(("reference_photo_p5", "photo_p5_source", "datasheet_p5_")) and not name.endswith(".pdf"):
                full = os.path.join(folder, name)
                archive.write(full, os.path.relpath(full, HERE))
print("done: " + zip_path)
