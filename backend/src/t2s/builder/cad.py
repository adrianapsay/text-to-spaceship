"""CAD for the CubeSat Builder: a part's CAD imported (STEP preferred; IGES, BREP or STL; a .zip holding them, even a
.zip of .zips, as some makers ship one per variant), checked and converted to a millimetre STL for the 3D preview and
the optimiser — or a simplified shape made from the catalog's published size. Every geometry says where it came from
(ORIGINS):

* "manufacturer"  — the maker's own CAD file;
* "reconstructed" — the user's model drawn from the maker's drawings;
* "bbox"          — a simplified bounding box of the published dimensions;
* "placeholder"   — a 20 mm stand-in when no size is published.

Files live in data/builder/cad, which git ignores: manufacturer CAD is licensed by its makers and is never committed
or pushed. The app never downloads CAD by itself; it imports what the user gives it.

STEP, IGES and BREP are read by OpenCASCADE (gmsh) in a separate process (python -I, a time limit, stopped when the
computer's free memory falls below the app's reserve), so a malformed or huge file cannot take the app or the machine
down; OpenCASCADE converts their units to millimetres. An STL has no units: its size is matched against the catalog's
published size (mm, cm, m or inch), else taken as millimetres and flagged. Checks on every import: which model of an
archive was used and why (pick_model; an archive often holds a part's variants); the file opens; it has solids (not
only surfaces); the surface mesh is closed (watertight); the mesh volume matches OpenCASCADE's within 2 %; the size
matches the catalog's within 10 % per axis (any orientation). The STL is moved so its bounding box is centred on the
origin (the shift is recorded: the maker's frame can be restored).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np

from ..core.fileio import atomic_write_text
from . import catalog as K
from .model import now_iso
from .store import ROOT as BUILDER_ROOT

ORIGINS = {"manufacturer": "Manufacturer CAD", "reconstructed": "Reconstructed from drawings",
           "bbox": "Simplified bounding box", "placeholder": "Placeholder"}
CAD_DIR = BUILDER_ROOT / "cad"
OCC_EXT = (".step", ".stp", ".iges", ".igs", ".brep")
MAX_BYTES = 200 * 1024 * 1024
TIMEOUT_S = 300.0
UNIT_SCALES = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
PLACEHOLDER_MM = 20.0
LICENCE = "the maker's licence terms apply; kept on this computer only (data/builder is git-ignored)"
ARCHIVE = "archive.zip"           # an imported archive holding several models, kept so another can be chosen
REPAIR_TEXT = {"as is": "none needed: the file's solids were meshed as they are",
               "fixed": "OpenCASCADE fixed small edges and faces (no sewing) before the surface mesh",
               "sewn": "OpenCASCADE sewed the surfaces into solids where it could before the surface mesh"}
KIND_ORDER = {".step": 0, ".stp": 0, ".iges": 1, ".igs": 1, ".brep": 1, ".stl": 2}
_WORD = re.compile(r"[a-z0-9]+")


class CadError(ValueError):
    """A CAD file that cannot be used, with the reason in plain words."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Extract a .zip into dest, refusing absolute paths, '..', links and more than 200 MB unpacked in all; returns the
    CAD files it held. A .zip inside it (some makers zip each variant) is unpacked the same way, one level deep, into a
    folder of its own name (models then read "outer/variant.zip/model.step")."""
    total = 0

    def unpack(zp: Path, into: Path, nested: bool) -> list[Path]:
        nonlocal total
        out = []
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                name = PurePosixPath(info.filename)
                if info.is_dir():
                    continue
                if name.is_absolute() or ".." in name.parts or ":" in info.filename or "\\" in info.filename:
                    raise CadError(f"the archive holds an unsafe path ({info.filename})")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise CadError(f"the archive holds a link ({info.filename})")
                total += info.file_size
                if total > MAX_BYTES:
                    raise CadError("the archive unpacks to more than 200 MB")
                target = into.joinpath(*name.parts)
                if not target.resolve().is_relative_to(into.resolve()):
                    raise CadError(f"the archive holds an unsafe path ({info.filename})")
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as f:
                    shutil.copyfileobj(src, f)
                kind = target.suffix.lower()
                if kind in OCC_EXT + (".stl",):
                    out.append(target)
                elif kind == ".zip" and nested:
                    packed = target.rename(target.with_name(target.name + ".part"))
                    try:
                        out += unpack(packed, target, nested=False)
                    except zipfile.BadZipFile as exc:
                        raise CadError(f"an archive inside it cannot be read ({info.filename})") from exc
                    packed.unlink()
        return out

    return unpack(zip_path, dest, nested=True)


def _words(text: str) -> list[str]:
    return _WORD.findall(str(text).lower())


def _aliases(product: str) -> list[str]:
    """The names a file of this part may carry, squashed to letters and digits: the product's first word, its model
    code (OPTIMUS-40 → optimus40), each '/' variant of it, and each name in brackets ("(BM 2)" → bm2)."""
    first = product.split()[0] if product.split() else ""
    out = []
    for g in (first, *first.split("/"), *re.findall(r"\(([^)]*)\)", product)):
        s = "".join(_words(g))
        if len(s) >= 3 and s not in out:
            out.append(s)
    return out


def pick_model(models: list[tuple[str, int]], product: str | None, member: str | None = None) -> tuple[int, dict]:
    """Which of an archive's CAD files (path in the archive, bytes) to import, and the "model" check saying why.

    `member` (its path in the archive, or its file name) chooses one. Otherwise STEP comes before IGES/BREP and those
    before STL; among them, first the file whose path carries the part's model name (_aliases), then the one with more
    of the product's words, then the one whose file name has fewer other words (a variant such as "PLUS"), then the
    largest (the main model, not a fixture). When those cannot tell the first two apart, or the file's name does not
    carry the part's, the check says so (ok None): the size check and the user decide."""
    names = [n for n, _ in models]
    label = product or "this part"

    def also(i: int) -> str:
        rest = [PurePosixPath(n).name for j, n in enumerate(names) if j != i]
        return f"; the archive also holds {', '.join(rest)}" if rest else ""

    if member:
        hits = [i for i, n in enumerate(names) if member in (n, PurePosixPath(n).name)]
        if len(hits) != 1:
            raise CadError(f"the archive holds no single model named {member}; it holds {', '.join(names)}")
        return hits[0], {"name": "model", "ok": True, "detail": f"{names[hits[0]]}: chosen{also(hits[0])}"}
    kind = [KIND_ORDER[PurePosixPath(n).suffix.lower()] for n in names]
    cands = [i for i in range(len(names)) if kind[i] == min(kind)]
    aliases = _aliases(product or "")
    pwords = {w for w in _words(product or "") if len(w) >= 2}

    def score(i: int) -> tuple:
        flat = "".join(_words(names[i]))
        others = [w for w in _words(PurePosixPath(names[i]).stem) if w.isalpha() and len(w) >= 3 and w not in pwords]
        return any(a in flat for a in aliases), sum(w in flat for w in pwords), -len(others)

    ranked = sorted(cands, key=lambda i: (score(i), models[i][1]), reverse=True)
    i = ranked[0]
    if len(ranked) > 1 and score(ranked[1]) == score(i):
        return i, {"name": "model", "ok": None,
                   "detail": f"{names[i]}: the names do not say which model is {label}; the largest was used{also(i)}"}
    if not score(i)[0]:
        return i, {"name": "model", "ok": None,
                   "detail": f"{names[i]}: its name does not name {label} — check that it is this part{also(i)}"}
    return i, {"name": "model", "ok": True, "detail": f"{names[i]}: its name matches {label}{also(i)}"}


def _tree(pid: int) -> list:
    """The process and its children: in a virtual environment on Windows, python.exe is a launcher that runs the real
    interpreter as its child, so the worker's memory is the child's and stopping it must reach the child."""
    try:
        import psutil
        p = psutil.Process(pid)
        return [p, *p.children(recursive=True)]
    except Exception:  # noqa: BLE001 - no psutil, or the process just ended
        return []


def _rss_mb(pid: int) -> float:
    total = 0
    for q in _tree(pid):
        with contextlib.suppress(Exception):          # a process that just ended
            total += q.memory_info().rss
    return total / 2 ** 20


def _stop(p: subprocess.Popen) -> None:
    for q in reversed(_tree(p.pid)):                   # the children first, then the launcher
        with contextlib.suppress(Exception):
            q.kill()
    if p.poll() is None:
        p.kill()


def occ_convert(src: Path, out_stl: Path, timeout: float = TIMEOUT_S) -> dict:
    """Run the conversion worker (OpenCASCADE) on src; its facts (with its peak memory, `peak_mb`), or CadError.

    The memory reserve every solve in the app keeps free (gd.layouts.MEM_RESERVE_MB) holds here too: the worker is not
    started when the computer has less available, and it is stopped when it runs past `timeout` or the available memory
    falls below the reserve while it runs, so a large assembly cannot starve the machine. Its output goes to files
    beside out_stl (an unread pipe could stall a reader that prints many warnings)."""
    from ..gd.layouts import MEM_RESERVE_MB, available_mb
    avail = available_mb()
    if avail is not None and avail < MEM_RESERVE_MB:
        raise CadError(f"the conversion was not started: {avail:.0f} MB of memory available and {MEM_RESERVE_MB:.0f} MB "
                       "must stay free — close other programs and import again")
    worker = Path(__file__).with_name("cad_worker.py")         # needs only gmsh: run by path, isolated (-I)
    log_out, log_err = out_stl.with_suffix(".out.txt"), out_stl.with_suffix(".err.txt")
    peak, why = 0.0, None
    with open(log_out, "w", encoding="utf-8") as fo, open(log_err, "w", encoding="utf-8") as fe:
        p = subprocess.Popen([sys.executable, "-I", str(worker), str(src), str(out_stl)],
                             stdout=fo, stderr=fe, cwd=str(out_stl.parent))
        t0 = time.monotonic()
        try:
            while p.poll() is None:
                peak = max(peak, _rss_mb(p.pid))
                avail = available_mb()
                if time.monotonic() - t0 > timeout:
                    why = f"the conversion took longer than {timeout:g} s"
                elif avail is not None and avail < MEM_RESERVE_MB:
                    why = (f"the conversion was stopped to keep {MEM_RESERVE_MB:.0f} MB of memory free "
                           f"({avail:.0f} MB available; the converter was using {peak:.0f} MB)")
                if why:
                    break
                time.sleep(0.25)
        finally:
            if p.poll() is None:
                _stop(p)
            p.wait()
    if why:
        raise CadError(why)
    lines = [ln for ln in log_out.read_text(encoding="utf-8", errors="replace").splitlines()
             if ln.strip().startswith("{")]
    if not lines:
        err = log_err.read_text(encoding="utf-8", errors="replace").strip()
        raise CadError(f"the converter stopped without an answer (exit {p.returncode}): {err[-300:]}")
    facts = json.loads(lines[-1])
    if "error" in facts:
        raise CadError(facts["error"])
    facts["peak_mb"] = round(peak, 1)
    return facts


def mesh_facts(stl: Path) -> dict:
    import trimesh
    m = trimesh.load(stl, force="mesh")
    if m.is_empty:
        raise CadError("the mesh is empty")
    lo, hi = m.bounds
    # the volume by the divergence theorem: right for a closed mesh, and for an assembly whose solids' surfaces are
    # each closed even where they touch (the merged mesh is then not "watertight"); a flat sheet has none
    with np.errstate(invalid="ignore", divide="ignore"):
        vol = float(abs(m.volume))
    return {"watertight": bool(m.is_watertight), "volume_mm3": vol,
            "bbox_mm": [lo.tolist(), hi.tolist()], "faces": len(m.faces), "mesh": m}


def size_match(extents, dims) -> bool | None:
    """Whether a box's extents match published dimensions within 10 % per axis in some orientation."""
    if dims is None:
        return None
    a, b = sorted(float(x) for x in extents), sorted(float(x) for x in dims)
    return all(abs(x - y) <= 0.10 * max(y, 1e-9) for x, y in zip(a, b, strict=True))


class CadStore:
    """The Builder's CAD files: data/builder/cad/<component id>/ with the STL, the source file and manifest.json."""

    def __init__(self, root: Path = CAD_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------------------ manifest
    def _manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def manifest(self) -> dict:
        p = self._manifest_path()
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def entry(self, cid: str) -> dict | None:
        return self.manifest().get(cid)

    def _put(self, cid: str, entry: dict | None) -> None:
        with self._lock:
            m = self.manifest()
            if entry is None:
                m.pop(cid, None)
            else:
                m[cid] = entry
            atomic_write_text(self._manifest_path(), json.dumps(m, indent=1))

    def _dir(self, cid: str) -> Path:
        if K.by_id(cid) is None and cid != "user-payload":
            raise KeyError(cid)
        return self.root / cid

    def stl_path(self, cid: str) -> Path:
        e = self.entry(cid)
        if e is None:
            raise KeyError(cid)
        return self.root / e["file"]

    def delete(self, cid: str) -> None:
        d = self._dir(cid)
        if d.is_dir():
            shutil.rmtree(d)
        self._put(cid, None)

    # ------------------------------------------------------------------------------------------ imports
    def import_file(self, cid: str, filename: str, data: bytes, origin: str = "manufacturer",
                    source_url: str | None = None, member: str | None = None) -> dict:
        """Check and convert a CAD file for catalog entry cid: STEP/IGES/BREP/STL, or a .zip holding them (`member`
        names the model to use, else pick_model chooses). An archive holding several models is kept, so another can be
        chosen later without uploading it again (choose_model)."""
        if origin not in ("manufacturer", "reconstructed"):
            raise CadError("an imported file is the maker's CAD or your reconstruction")
        if len(data) > MAX_BYTES:
            raise CadError("the file is larger than 200 MB")
        name = Path(filename or "part").name
        ext = Path(name).suffix.lower()
        if ext not in OCC_EXT + (".stl", ".zip"):
            raise CadError(f"{ext or 'no extension'}: send STEP (.step/.stp), IGES, BREP, STL or a .zip of one")
        if member and ext != ".zip":
            raise CadError("a model can be chosen only from a .zip archive")
        d = self._dir(cid)
        work = d / "incoming"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        try:
            return self._convert(cid, d, work, name, data, origin, source_url, member)
        finally:
            shutil.rmtree(work, ignore_errors=True)          # the unpacked files go, imported or not

    def choose_model(self, cid: str, member: str) -> dict:
        """Import another model from the archive kept at the part's last import (one that held several)."""
        kept = self._dir(cid) / ARCHIVE
        e = self.entry(cid)
        if e is None or not kept.is_file():
            raise CadError("no archive holding several models was imported for this part")
        return self.import_file(cid, e["source_name"], kept.read_bytes(), e["origin"], e.get("source_url"), member)

    def _convert(self, cid: str, d: Path, work: Path, name: str, data: bytes, origin: str, source_url: str | None,
                 member: str | None) -> dict:
        upload = work / name
        upload.write_bytes(data)
        src, ext = upload, upload.suffix.lower()
        c = K.by_id(cid)
        checks, models, chosen = [], [], None
        if ext == ".zip":
            top = work / "unzipped"
            try:
                found = safe_extract(upload, top)
            except (zipfile.BadZipFile, OSError) as exc:
                raise CadError(f"not a readable .zip archive ({exc})") from exc
            if not found:
                raise CadError("the archive holds no STEP, IGES, BREP or STL file")
            models = [p.relative_to(top).as_posix() for p in found]
            i, check = pick_model([(m, p.stat().st_size) for m, p in zip(models, found, strict=True)],
                                  c["product"] if c else None, member)
            checks.append(check)
            src, chosen = found[i], models[i]
            ext = src.suffix.lower()
        dims = K.dims_mm(c) if c else None
        out = work / f"{cid}.stl"
        if ext in OCC_EXT:
            facts = occ_convert(src, out)
            checks.append({"name": "opens", "ok": True, "detail": "read by OpenCASCADE; units converted to mm"})
            checks.append({"name": "solids", "ok": facts["solids"] > 0,
                           "detail": f"{facts['solids']} solid(s), {facts['surfaces']} surface(s)" +
                                     ("" if facts["solids"] else ": surfaces only, no closed volume")})
            first = f" (the first mesh failed: {facts['mesh_error']})" if facts.get("mesh_error") else ""
            checks.append({"name": "repair", "ok": True, "detail": REPAIR_TEXT.get(facts.get("repair"), "—") + first})
            units, scale = "mm (converted by OpenCASCADE)", 1.0
        else:
            facts = {"solids": None, "volume_mm3": None}
            shutil.copyfile(src, out)
            raw = mesh_facts(out)
            ext_raw = np.subtract(raw["bbox_mm"][1], raw["bbox_mm"][0])
            scale = next((s for u, s in UNIT_SCALES.items() if size_match(ext_raw * s, dims)), None)
            if scale is None:
                scale = 1.0
                units = "mm (ASSUMED: an STL has no units" + (" and its size matches no unit against the catalog)"
                                                             if dims else " and the catalog has no size to check)")
            else:
                units = f"{next(u for u, s in UNIT_SCALES.items() if s == scale)} (matched the catalog's size)"
            checks.append({"name": "opens", "ok": True, "detail": "read as STL"})
        mf = mesh_facts(out)
        mesh = mf.pop("mesh")
        mesh.apply_scale(scale)
        lo, hi = mesh.bounds
        shift = -(lo + hi) / 2.0
        mesh.apply_translation(shift)
        final = d / f"{cid}.stl"
        mesh.export(final)
        extents = (hi - lo).tolist()
        vol_ok, err = None, None
        if facts.get("volume_mm3") and mf["volume_mm3"]:
            err = abs(mf["volume_mm3"] - facts["volume_mm3"]) / facts["volume_mm3"]
            vol_ok = err <= 0.02
        n = facts.get("solids") or 0
        if mf["watertight"]:
            checks.append({"name": "watertight", "ok": True, "detail": "the surface mesh is closed"})
        elif vol_ok and n > 1:
            checks.append({"name": "watertight", "ok": None,
                           "detail": f"not closed as one surface, as usual for an assembly of {n} solids that touch "
                                     "(edges shared by more than two triangles); the volume matches OpenCASCADE's, so "
                                     "the solids' surfaces enclose them"})
        else:
            checks.append({"name": "watertight", "ok": False,
                           "detail": "the surface mesh has open edges: its volume and mass properties are not reliable"})
        if vol_ok is not None:
            checks.append({"name": "volume", "ok": vol_ok,
                           "detail": f"mesh {mf['volume_mm3']:.0f} mm³ vs OpenCASCADE {facts['volume_mm3']:.0f} mm³ "
                                     f"({100 * err:.2f} %)"})
        sm = size_match(extents, dims)
        checks.append({"name": "size", "ok": sm,
                       "detail": (f"{' × '.join(f'{x:.1f}' for x in extents)} mm against the catalog's "
                                  f"{' × '.join(f'{x:g}' for x in dims)} mm" if dims else
                                  "the catalog publishes no size to compare")})
        for old in d.glob("source.*"):
            old.unlink()
        shutil.copyfile(src, d / f"source{ext}")
        if len(models) > 1:
            shutil.copyfile(upload, d / ARCHIVE)
        else:
            (d / ARCHIVE).unlink(missing_ok=True)
        entry = {"component": cid, "origin": origin, "origin_text": ORIGINS[origin], "file": f"{cid}/{cid}.stl",
                 "source_name": name, "source_file": f"{cid}/source{ext}", "source_url": source_url,
                 "archive_models": models, "archive_member": chosen,
                 "sha256": _sha256(data), "imported": now_iso(), "units": units, "scale": scale,
                 "extents_mm": extents, "shift_mm": (shift * 1.0).tolist(),
                 "volume_mm3": float(abs(mesh.volume)) if mf["watertight"] or vol_ok else None,
                 "solids": facts.get("solids"), "faces": mf["faces"], "converter_peak_mb": facts.get("peak_mb"),
                 "checks": checks, "ok": all(ch["ok"] is not False for ch in checks), "licence": LICENCE}
        self._put(cid, entry)
        return entry

    def simplified(self, cid: str) -> dict:
        """A bounding box of the catalog's published size (or a placeholder cube when none is published)."""
        import trimesh
        c = K.by_id(cid)
        if c is None:
            raise KeyError(cid)
        dims = K.dims_mm(c)
        origin = "bbox" if dims else "placeholder"
        ext = list(dims) if dims else [PLACEHOLDER_MM] * 3
        d = self._dir(cid)
        d.mkdir(parents=True, exist_ok=True)
        box = trimesh.creation.box(extents=ext)
        box.export(d / f"{cid}.stl")
        entry = {"component": cid, "origin": origin, "origin_text": ORIGINS[origin], "file": f"{cid}/{cid}.stl",
                 "source_name": None, "source_file": None, "source_url": None, "sha256": None,
                 "imported": now_iso(), "units": "mm", "scale": 1.0, "extents_mm": [float(x) for x in ext],
                 "shift_mm": [0.0, 0.0, 0.0], "volume_mm3": float(np.prod(ext)), "solids": 1, "faces": 12,
                 "checks": [{"name": "size", "ok": True if dims else None,
                             "detail": "the catalog's published size" if dims else
                             f"no size published: a {PLACEHOLDER_MM:g} mm placeholder cube"}],
                 "ok": True, "licence": None}
        self._put(cid, entry)
        return entry

    def geometry(self, cid: str) -> dict:
        """The geometry a part uses: its imported CAD if any, else a simplified shape made now."""
        e = self.entry(cid)
        return e if e is not None else self.simplified(cid)
