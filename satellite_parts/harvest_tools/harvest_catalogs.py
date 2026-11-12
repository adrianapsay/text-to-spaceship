"""
Pass 6 (v2): broad harvest of small-satellite components from two public catalogs that mirror vendor datasheets:
satcatalog.com (crawled through its vendor and component pages) and satsearch.co (sitemap, else crawled through supplier pages).

    python harvest_catalogs.py

1. Discovers component / product pages (no sitemap needed for satcatalog; the crawl follows vendor -> components -> component links).
2. Visits each page: name, vendor, the page text (satsearch pages carry the spec table with dimensions and mass), datasheet link, product image.
3. Downloads the datasheet PDF (text + page 1 PNG) and the product image for parts we do not already have (known_models.txt).
4. Writes pass6_light.zip (index, page texts, datasheet texts, PNGs, photos; no PDFs) and refreshes it every 150 downloads,
   so a partial run is still useful. Safe to re-run: everything already fetched is skipped.
Runs up to MAX_MINUTES (default 150) and then packs what it has.
"""
import os
import re
import io
import sys
import csv
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

MAX_MINUTES = 150
MAX_PAGES = 4500
MAX_DOWNLOADS = 1200
started = time.time()
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
session = requests.Session()
session.headers.update(headers)
out_root = os.path.join(HERE, "pass6")
os.makedirs(out_root, exist_ok=True)
log = open(os.path.join(HERE, "pass6_log.txt"), "a", encoding="utf-8")


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


def text_of(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", "\n", html)
    for entity, value in (("&amp;", "&"), ("&nbsp;", " "), ("&#8211;", "-"), ("&#039;", "'"), ("&quot;", '"'), ("&times;", "x"), ("&#215;", "x")):
        text = text.replace(entity, value)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def links_in(html, base):
    result = []
    for link in re.findall(r'href=["\']([^"\'#]+)["\']', html, flags=re.I):
        link = link.replace("&amp;", "&").strip()
        if link.startswith("//"):
            link = "https:" + link
        elif link.startswith("/"):
            link = re.match(r"https?://[^/]+", base).group(0) + link
        elif not link.startswith("http"):
            continue
        result.append(link)
    return result


def slug_of(url):
    return re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower()).strip("-")


known = set()
if os.path.exists(os.path.join(HERE, "known_models.txt")):
    known = set(line.strip().lower() for line in open(os.path.join(HERE, "known_models.txt"), encoding="utf-8") if line.strip())

# 1. discovery. satcatalog: crawl listing pages first, then component pages (which link their vendor, whose component list is crawled too).
component_urls = []
seen_pages = set()
listing_queue = ["https://satcatalog.com/vendors/", "https://satcatalog.com/components/", "https://satcatalog.com/", "https://satcatalog.com/vendor/bradford-space/components/"]
component_queue = ["https://satcatalog.com/component/1n-hpgp/", "https://satcatalog.com/component/rw8/", "https://satcatalog.com/component/mai-400/", "https://satcatalog.com/component/cfc-400/", "https://satcatalog.com/component/triscape200/"]
page_count = 0
while (listing_queue or component_queue) and page_count < 2500 and minutes() < 45:
    url = listing_queue.pop(0) if listing_queue else component_queue.pop(0)
    if url in seen_pages:
        continue
    seen_pages.add(url)
    content = get(url)
    page_count = page_count + 1
    if not content:
        continue
    html = content.decode("utf-8", "ignore")
    for link in links_in(html, url):
        if "satcatalog.com" not in link:
            continue
        if "/component/" in link:
            link = link.split("?")[0]
            if link not in component_urls:
                component_urls.append(link)
                component_queue.append(link)
        elif re.search(r"satcatalog\.com/vendor/[^/]+/?$", link):
            listing_queue.append(link.rstrip("/") + "/components/")
        elif re.search(r"satcatalog\.com/(vendors|components|vendor/[^/]+/components)/?", link) or "page=" in link or "/page/" in link:
            if link not in seen_pages:
                listing_queue.append(link)
    if page_count % 50 == 0:
        say("satcatalog discovery: " + str(page_count) + " pages read, " + str(len(component_urls)) + " components found")
say("satcatalog discovery done: " + str(len(component_urls)) + " component pages")

product_urls = []
seen_maps = set()
maps = ["https://satsearch.co/sitemap.xml", "https://satsearch.co/sitemap_index.xml", "https://satsearch.co/sitemaps/sitemap.xml", "https://satsearch.co/products-sitemap.xml"]
while maps and len(seen_maps) < 80:
    map_url = maps.pop(0)
    if map_url in seen_maps:
        continue
    seen_maps.add(map_url)
    content = get(map_url)
    if not content:
        continue
    for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", content.decode("utf-8", "ignore")):
        loc = loc.replace("&amp;", "&")
        if "/products/" in loc and "/categories/" not in loc:
            if loc not in product_urls:
                product_urls.append(loc)
        elif loc.endswith(".xml") or "sitemap" in loc:
            maps.append(loc)
if not product_urls:
    queue = ["https://satsearch.co/suppliers", "https://satsearch.co/products", "https://satsearch.co/"]
    seen = set()
    while queue and len(seen) < 600 and minutes() < 60:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        content = get(url)
        if not content:
            continue
        for link in links_in(content.decode("utf-8", "ignore"), url):
            if "satsearch.co" not in link:
                continue
            if re.search(r"satsearch\.co/products/[a-z0-9-]+/?$", link) and "/categories" not in link:
                if link not in product_urls:
                    product_urls.append(link)
            elif re.search(r"satsearch\.co/(suppliers(/[a-z0-9-]+)?|products/categories/[a-z0-9/-]+)/?(\?page=\d+)?$", link):
                queue.append(link)
say("satsearch discovery done: " + str(len(product_urls)) + " product pages")

# 2. visit pages (index cached in pass6_index.csv)
index_path = os.path.join(HERE, "pass6_index.csv")
fields = ["url", "slug", "source", "name", "vendor", "datasheet", "image", "has_text"]
index = {}
if os.path.exists(index_path):
    for row in csv.DictReader(open(index_path, encoding="utf-8")):
        index[row["url"]] = row


def write_index():
    with open(index_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(index.values())


pages = [(url, "satcatalog") for url in component_urls] + [(url, "satsearch") for url in product_urls]
say(str(len(pages)) + " pages to index (cap " + str(MAX_PAGES) + ")")
visited = 0
for url, source in pages[:MAX_PAGES]:
    if url in index or minutes() > MAX_MINUTES * 0.55:
        continue
    slug = source + "__" + slug_of(url)
    row = {"url": url, "slug": slug, "source": source, "name": "", "vendor": "", "datasheet": "", "image": "", "has_text": "no"}
    content = get(url)
    if content:
        html = content.decode("utf-8", "ignore")
        title = re.search(r"<title>([^<]+)</title>", html, flags=re.I)
        row["name"] = title.group(1).strip()[:150] if title else slug
        vendor = re.search(r'href="https?://(?:www\.)?(?:satcatalog\.com/vendor|satsearch\.co/suppliers)/([^/"?]+)', html)
        row["vendor"] = vendor.group(1) if vendor else ""
        sheets = re.findall(r'(https?://(?:satcatalog|satsearch)[a-z0-9.-]*\.amazonaws\.com/[^"\'\s<>]+?\.pdf[^"\'\s<>]*)', html)
        if not sheets:
            sheets = [link for link in links_in(html, url) if ".pdf" in link.lower() and ("datasheet" in link.lower() or "data-sheet" in link.lower() or "brochure" in link.lower())]
        row["datasheet"] = sheets[0].replace("&amp;", "&") if sheets else ""
        image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I) or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, flags=re.I)
        row["image"] = image.group(1).replace("&amp;", "&") if image else ""
        page_text = text_of(html)
        open(os.path.join(out_root, "_page__" + slug + ".txt"), "w", encoding="utf-8").write(url + "\n" + page_text[:12000])
        row["has_text"] = "yes"
    index[url] = row
    visited = visited + 1
    if visited % 100 == 0:
        write_index()
        say("indexed " + str(len(index)) + " pages  (" + str(int(minutes())) + " min)")
    time.sleep(0.15)
write_index()


# 3. downloads
def pack():
    zip_path = os.path.join(HERE, "pass6_light.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(index_path, "pass6_index.csv")
        archive.write(os.path.join(HERE, "pass6_log.txt"), "pass6_log.txt")
        for root, folders, files in os.walk(out_root):
            for name in files:
                if name.endswith((".txt", ".png", ".jpg")):
                    full = os.path.join(root, name)
                    archive.write(full, os.path.relpath(full, HERE))
    say("packed " + zip_path)


candidates = [row for row in index.values() if row.get("datasheet") or row.get("image")]
candidates = [row for row in candidates if slug_of(row["url"]) not in known]
say(str(len(candidates)) + " candidate parts with a datasheet or image")
downloaded = 0
for row in candidates[:MAX_DOWNLOADS]:
    if minutes() > MAX_MINUTES:
        say("time limit reached")
        break
    folder = os.path.join(out_root, row["slug"])
    os.makedirs(folder, exist_ok=True)
    pdf_path = os.path.join(folder, "datasheet.pdf")
    if row.get("datasheet") and not os.path.exists(pdf_path):
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
    if row.get("image") and not os.path.exists(os.path.join(folder, "photo.jpg")):
        content = get(row["image"])
        if content:
            try:
                image = Image.open(io.BytesIO(content))
                image.load()
                if image.width >= 200 and image.height >= 200:
                    if image.mode in ("RGBA", "LA", "P"):
                        image = image.convert("RGBA")
                        background = Image.new("RGB", image.size, (255, 255, 255))
                        background.paste(image, mask=image.split()[-1])
                        image = background
                    else:
                        image = image.convert("RGB")
                    image.thumbnail((800, 800))
                    image.save(os.path.join(folder, "photo.jpg"), "JPEG", quality=85)
            except Exception:
                pass
    open(os.path.join(folder, "source.txt"), "w", encoding="utf-8").write("page: " + row["url"] + "\ndatasheet: " + row.get("datasheet", "") + "\nimage: " + row.get("image", "") + "\nfetched by harvest_catalogs.py on " + time.strftime("%Y-%m-%d") + "\n")
    downloaded = downloaded + 1
    if downloaded % 25 == 0:
        say("downloaded " + str(downloaded) + "/" + str(min(len(candidates), MAX_DOWNLOADS)) + "  (" + str(int(minutes())) + " min)")
    if downloaded % 150 == 0:
        pack()
    time.sleep(0.15)
pack()
say("done")
