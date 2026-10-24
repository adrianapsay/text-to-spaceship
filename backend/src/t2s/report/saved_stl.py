"""V2 saved STL files: the designed assembly of the best layout, kept in the project folder (<project>/saved_stl/).

* What: every part and every bracket that has a real solid (built, or designed by the bracket design job) as binary
  STL in world coordinates (mm), the whole assembly in one file (assembly.stl), manifest.json (the layout, the
  settings it was found at, what each file is) and README.txt. Brackets still drawn as their reserved box or
  catalogue envelope are left out and listed as such.
* When: the coordinator writes the set when a bracket design run finishes on the best layout, when the search pauses
  on a best layout whose brackets were designed before, and when the Mounting Hardware tab asks for it.
* Sliders: when a slider (or another search setting) moves, the bracket files are deleted and assembly.stl is written
  again from the parts alone — those brackets were designed for the layout found at the old settings. The next
  finished design run (or pause on a designed layout) saves them again.
"""
from __future__ import annotations

import io
import json
import shutil
import struct
import zipfile
from datetime import datetime
from pathlib import Path

from ..core.fileio import atomic_write_text

FOLDER = "saved_stl"
MANIFEST = "manifest.json"
_HEAD = 80                   # binary STL: 80-byte header, uint32 triangle count, 50 bytes per triangle


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def triangles(stl: bytes) -> bytes:
    """The triangle records of a binary STL file — what it adds to an assembly."""
    n = struct.unpack_from("<I", stl, _HEAD)[0]
    return stl[_HEAD + 4:_HEAD + 4 + 50 * n]


def assembly_bytes(chunks: list[bytes], header: str) -> bytes:
    body = b"".join(chunks)
    return header.encode("ascii", "replace")[:_HEAD].ljust(_HEAD, b" ") + struct.pack("<I", len(body) // 50) + body


def read_manifest(folder: Path) -> dict | None:
    try:
        return json.loads((Path(folder) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _readme(m: dict) -> str:
    s = m.get("settings") or {}
    lines = [f"TEXT-TO-SPACESHIP V2 - saved STL files of layout {m['layout_id']} (saved {m['saved_at']})",
             (f"Settings: {s.get('form_factor', '?')}, part size {s.get('part_scale_pct', '?')} %, Stage "
              f"{s.get('stage', '?')}, bracket budget {(s.get('sliders') or {}).get('bracket_budget', '?')}."),
             "Units: millimetres, world frame of the layout (origin at the envelope centre).",
             ("assembly.stl: every part and bracket below in one file. parts/: one file per part. brackets/: one file "
              "per bracket (AM_* metal 3D-printed, designed by the bracket design job)."),
             ("When a slider or another search setting moves, the bracket files are deleted and assembly.stl is written "
              "again without them; the next finished bracket design run saves them again."), "",
             "Files:", "assembly.stl", *[r["file"] for r in m.get("parts", [])],
             *[r["file"] for r in m.get("brackets", [])]]
    if m.get("left_out"):
        lines += ["", "Left out (no real solid yet: reserved box or catalogue envelope):",
                  *[f"{r.get('part', r.get('part_id'))}: {r.get('kind')} - {r.get('why', '')}" for r in m["left_out"]]]
    if m.get("brackets_removed"):
        lines += ["", f"Brackets removed {m['brackets_removed']['at']}: {m['brackets_removed']['reason']}"]
    return "\n".join(lines) + "\n"


def write_set(folder: Path, layout_id: str, parts: list[tuple[str, bytes, dict]],
              brackets: list[tuple[str, bytes, dict]], info: dict) -> dict:
    """Replace the saved set. parts / brackets: (file stem, binary STL in world mm, description). info: extra manifest
    fields (settings, left_out, why the set was written). Returns the manifest."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rows = {}
    for sub, items in (("parts", parts), ("brackets", brackets)):
        shutil.rmtree(folder / sub, ignore_errors=True)
        (folder / sub).mkdir(parents=True, exist_ok=True)
        rows[sub] = []
        for stem, data, desc in items:
            fn = f"{sub}/{stem}.stl"
            (folder / fn).write_bytes(data)
            rows[sub].append({**desc, "file": fn, "triangles": len(triangles(data)) // 50})
    chunks = [triangles(data) for _, data, _ in [*parts, *brackets]]
    (folder / "assembly.stl").write_bytes(assembly_bytes(chunks, f"t2s {layout_id} assembly world mm"))
    m = {"layout_id": layout_id, "saved_at": now_text(), "status": "complete", **info, "assembly": "assembly.stl",
         "parts": rows["parts"], "brackets": rows["brackets"], "brackets_removed": None, "removed_brackets": []}
    (folder / "README.txt").write_text(_readme(m), encoding="utf-8")
    atomic_write_text(folder / MANIFEST, json.dumps(m, indent=1))
    return m


def remove_brackets(folder: Path, reason: str) -> dict | None:
    """Delete the saved bracket files and write assembly.stl again from the saved parts alone. Returns the updated
    manifest, or None when there is no saved set or it has no brackets left to remove."""
    folder = Path(folder)
    m = read_manifest(folder)
    if not m or not m.get("brackets"):
        return None
    shutil.rmtree(folder / "brackets", ignore_errors=True)
    chunks = []
    for r in m.get("parts", []):
        try:
            chunks.append(triangles((folder / r["file"]).read_bytes()))
        except OSError:
            continue
    (folder / "assembly.stl").write_bytes(assembly_bytes(chunks, f"t2s {m['layout_id']} parts only world mm"))
    m.update(status="brackets_removed", removed_brackets=m["brackets"], brackets=[],
             brackets_removed={"at": now_text(), "reason": reason})
    (folder / "README.txt").write_text(_readme(m), encoding="utf-8")
    atomic_write_text(folder / MANIFEST, json.dumps(m, indent=1))
    return m


def zip_set(folder: Path) -> bytes:
    """The saved set as one zip: assembly.stl, parts/, brackets/, manifest.json, README.txt."""
    folder = Path(folder)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and not p.name.endswith(".tmp"):
                z.write(p, p.relative_to(folder).as_posix())
    return buf.getvalue()
