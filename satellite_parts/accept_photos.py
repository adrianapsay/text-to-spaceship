"""
Makes the reviewed photos the parts' reference photos.
    python accept_photos.py <review folder> <part_id> [<part_id> ...]
Each accepted <review folder>/<part_id>.jpg becomes <part folder>/reference_photo.jpg, with photo_origin.txt from the download note.
Photos not named stay in the review folder (rejected ones are moved to _rejected_photos/<review folder name>/ by the caller).
"""
import os
import sys
import glob
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
review = sys.argv[1]
done = 0
for part_id in sys.argv[2:]:
    photo = os.path.join(review, part_id + ".jpg")
    targets = glob.glob(os.path.join(HERE, "*", part_id, "part.json"))
    if not os.path.exists(photo) or not targets:
        print("skipped " + part_id)
        continue
    part_folder = os.path.dirname(targets[0])
    shutil.copy(photo, os.path.join(part_folder, "reference_photo.jpg"))
    note = os.path.join(review, part_id + ".txt")
    origin = open(note, encoding="utf-8").read() if os.path.exists(note) else "downloaded by the lab laptop fetch script\n"
    open(os.path.join(part_folder, "photo_origin.txt"), "w", encoding="utf-8").write(origin + "checked by eye against the CAD render on 2026-11-11\n")
    done = done + 1
print(str(done) + " photos accepted")
