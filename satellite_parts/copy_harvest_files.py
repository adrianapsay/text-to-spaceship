"""
Copies the files staged for harvested parts (_harvest_files/<part id>/: datasheet page PNG, datasheet text and source, photo and photo origin)
into the part folders that generate_parts.py made. Run after generate_parts.py.
    python copy_harvest_files.py
"""
import os
import glob
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
copied = 0
missing = []
for staged_folder in sorted(glob.glob(os.path.join(HERE, "_harvest_files", "*"))):
    part_id = os.path.basename(staged_folder)
    targets = glob.glob(os.path.join(HERE, "*", part_id, "part.json"))
    if not targets:
        missing.append(part_id)
        continue
    part_folder = os.path.dirname(targets[0])
    for path in glob.glob(os.path.join(staged_folder, "*")):
        shutil.copy(path, os.path.join(part_folder, os.path.basename(path)))
        copied = copied + 1
print("copied " + str(copied) + " files; parts not generated yet: " + str(len(missing)))
