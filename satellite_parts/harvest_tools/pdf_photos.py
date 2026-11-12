import os, sys, glob, subprocess, shutil
from PIL import Image
base = sys.argv[1]; slugs = [s.strip() for s in open(sys.argv[2]) if s.strip()]; out = sys.argv[3]
os.makedirs(out, exist_ok=True)
for slug in slugs:
    pdf = os.path.join(base, "pass6", slug, "datasheet.pdf")
    if not os.path.exists(pdf):
        print(slug, "no pdf"); continue
    tmp = "/tmp/pdfimg_" + slug
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    subprocess.run(["pdfimages", "-f", "1", "-l", "2", "-png", pdf, tmp + "/i"], timeout=60, capture_output=True)
    best, best_area = None, 0
    for path in glob.glob(tmp + "/*.png"):
        try:
            image = Image.open(path); image.load()
        except Exception:
            continue
        ratio = image.width / float(image.height)
        small = image.convert("RGB").resize((64, 64))
        colors = len(set(small.getdata()))
        from PIL import ImageStat
        spread = sum(ImageStat.Stat(small).stddev) / 3.0
        if colors < 200 or spread < 25:
            continue
        if image.width >= 200 and image.height >= 200 and 0.3 < ratio < 3.5 and image.width * image.height > best_area:
            best, best_area = image, image.width * image.height
    if best is None:
        print(slug, "no picture"); continue
    if best.mode in ("RGBA", "LA", "P"):
        best = best.convert("RGBA"); background = Image.new("RGB", best.size, (255, 255, 255)); background.paste(best, mask=best.split()[-1]); best = background
    else:
        best = best.convert("RGB")
    best.thumbnail((800, 800)); best.save(os.path.join(out, slug + ".jpg"), "JPEG", quality=85)
    print(slug, "ok", best.size)
    shutil.rmtree(tmp, ignore_errors=True)
