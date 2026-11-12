"""
Imports a light zip made by fetch_pass5.py / fetch_pass7.py / fetch_pass8_parts.py on the lab laptop.
    python import_fetch_zip.py <unzipped folder> <tag, e.g. p7>
1. Datasheets: datasheet_p5_N_page1.png, _source.txt and .txt go into the part folder as datasheet_<tag>_N_*; the text is also written to
   _relevance_texts/<part>__datasheet_<tag>_N.txt for check_datasheet_relevance.py.
2. Photos: reference_photo_p5.jpg is NOT used yet; it is copied to _photo_review/<part>.jpg with its source note, for the by-eye check
   (accept_photos.py then makes it the part's reference_photo.jpg).
"""
import os
import sys
import glob
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
source_root = sys.argv[1]
tag = sys.argv[2]
texts = os.path.join(HERE, "_relevance_texts_" + tag)
review = os.path.join(HERE, "_photo_review_" + tag)
os.makedirs(texts, exist_ok=True)
os.makedirs(review, exist_ok=True)
datasheets = 0
photos = 0
for folder in sorted(glob.glob(os.path.join(source_root, "photos", "*", "*"))):
    part_id = os.path.basename(folder)
    targets = glob.glob(os.path.join(HERE, "*", part_id, "part.json"))
    if not targets:
        continue
    part_folder = os.path.dirname(targets[0])
    for page in glob.glob(os.path.join(folder, "datasheet_p5_*_page1.png")):
        number = os.path.basename(page).split("_")[2]
        stem_in = os.path.join(folder, "datasheet_p5_" + number)
        stem_out = "datasheet_" + tag + "_" + number
        if os.path.exists(os.path.join(part_folder, stem_out + "_page1.png")):
            continue
        shutil.copy(page, os.path.join(part_folder, stem_out + "_page1.png"))
        for suffix in ("_source.txt", ".txt"):
            if os.path.exists(stem_in + suffix):
                shutil.copy(stem_in + suffix, os.path.join(part_folder, stem_out + suffix))
        if os.path.exists(stem_in + ".txt"):
            shutil.copy(stem_in + ".txt", os.path.join(texts, part_id + "__" + stem_out + ".txt"))
        datasheets = datasheets + 1
    photo = os.path.join(folder, "reference_photo_p5.jpg")
    if os.path.exists(photo) and not os.path.exists(os.path.join(part_folder, "reference_photo.jpg")):
        shutil.copy(photo, os.path.join(review, part_id + ".jpg"))
        note = os.path.join(folder, "photo_p5_source.txt")
        if os.path.exists(note):
            shutil.copy(note, os.path.join(review, part_id + ".txt"))
        photos = photos + 1
print(str(datasheets) + " datasheets placed, " + str(photos) + " photos waiting for review in " + review)
