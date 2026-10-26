"""CAD for the CubeSat Builder: a part's CAD imported (STEP preferred; IGES, BREP or STL; a .zip holding one), checked
and converted to a millimetre STL for the 3D preview and the optimiser — or a simplified shape made from the
catalog's published size. Every geometry says where it came from (ORIGINS):

* "manufacturer"  — the maker's own CAD file;
* "reconstructed" — the user's model drawn from the maker's drawings;
* "bbox"          — a simplified bounding box of the published dimensions;
* "placeholder"   — a 20 mm stand-in when no size is published.

Files live in data/builder/cad, which git ignores: manufacturer CAD is licensed by its makers and is never committed
or pushed. The app never downloads CAD by itself; it imports what the user gives it.

STEP, IGES and BREP are read by OpenCASCADE (gmsh) in a separate process (python -I, a time limit), so a malformed
file cannot take the app down; OpenCASCADE converts their units to millimetres. An STL has no units: its size is
matched against the catalog's published size (mm, cm, m or inch), else taken as millimetres and flagged. Checks on
every import: the file opens; it has solids (not only surfaces); the surface mesh is closed (watertight); the mesh
volume matches OpenCASCADE's within 2 %; the size matches the catalog's within 10 % per axis (any orientation).
The STL is moved so its bounding box is centred on the origin (the shift is recorded: the maker's frame can be
restored).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
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


class CadError(ValueError):
    """A CAD file that cannot be used, with the reason in plain words."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Extract a .zip into dest, refusing absolute paths, '..' and links; returns the CAD files it held."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        total = 0
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
            target = dest.joinpath(*name.parts)
            if not target.resolve().is_relative_to(dest.resolve()):
                raise CadError(f"the archive holds an unsafe path ({info.filename})")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as f:
                shutil.copyfileobj(src, f)
            if target.suffix.lower() in OCC_EXT + (".stl",):
                out.append(target)
    return out


def occ_convert(src: Path, out_stl: Path, timeout: float = TIMEOUT_S) -> dict:
    """Run the conversion worker (OpenCASCADE) on src; its facts, or CadError."""
    worker = Path(__file__).with_name("cad_worker.py")         # needs only gmsh: run by path, isolated (-I)
    try:
        p = subprocess.run([sys.executable, "-I", str(worker), str(src), str(out_stl)], check=False,
                           capture_output=True, text=True, timeout=timeout, cwd=str(out_stl.parent))
    except subprocess.TimeoutExpired as exc:
        raise CadError(f"the conversion took longer than {timeout:g} s") from exc
    lines = [ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        raise CadError(f"the converter stopped without an answer (exit {p.returncode}): {p.stderr.strip()[-300:]}")
    facts = json.loads(lines[-1])
    if "error" in facts:
        raise CadError(facts["error"])
    return facts


def mesh_facts(stl: Path) -> dict:
    import trimesh
    m = trimesh.load(stl, force="mesh")
    if m.is_empty:
        raise CadError("the mesh is empty")
    lo, hi = m.bounds
    return {"watertight": bool(m.is_watertight), "volume_mm3": float(abs(m.volume)) if m.is_watertight else None,
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
                    source_url: str | None = None) -> dict:
        """Check and convert a CAD file for catalog entry cid (STEP/IGES/BREP/STL, or a .zip holding one)."""
        if origin not in ("manufacturer", "reconstructed"):
            raise CadError("an imported file is the maker's CAD or your reconstruction")
        if len(data) > MAX_BYTES:
            raise CadError("the file is larger than 200 MB")
        name = Path(filename or "part").name
        ext = Path(name).suffix.lower()
        if ext not in OCC_EXT + (".stl", ".zip"):
            raise CadError(f"{ext or 'no extension'}: send STEP (.step/.stp), IGES, BREP, STL or a .zip of one")
        d = self._dir(cid)
        work = d / "incoming"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        src = work / name
        src.write_bytes(data)
        if ext == ".zip":
            try:
                found = safe_extract(src, work / "unzipped")
            except zipfile.BadZipFile as exc:
                raise CadError("not a readable .zip archive") from exc
            step = [p for p in found if p.suffix.lower() in (".step", ".stp")]
            pick = step or [p for p in found if p.suffix.lower() in OCC_EXT] or found
            if not pick:
                raise CadError("the archive holds no STEP, IGES, BREP or STL file")
            src = max(pick, key=lambda p: p.stat().st_size)          # the main model, not a fixture
            ext = src.suffix.lower()
        c = K.by_id(cid)
        dims = K.dims_mm(c) if c else None
        out = work / f"{cid}.stl"
        checks = []
        if ext in OCC_EXT:
            facts = occ_convert(src, out)
            checks.append({"name": "opens", "ok": True, "detail": "read by OpenCASCADE; units converted to mm"})
            checks.append({"name": "solids", "ok": facts["solids"] > 0,
                           "detail": f"{facts['solids']} solid(s), {facts['surfaces']} surface(s)" +
                                     ("" if facts["solids"] else ": surfaces only, no closed volume")})
            checks.append({"name": "healing", "ok": facts["healed"], "detail": "OpenCASCADE shape healing ran"
                           if facts["healed"] else "shape healing could not run"})
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
        checks.append({"name": "watertight", "ok": mf["watertight"],
                       "detail": "the surface mesh is closed" if mf["watertight"] else
                       "the surface mesh has open edges: its volume and mass properties are not reliable"})
        if facts.get("volume_mm3") and mf["volume_mm3"]:
            err = abs(mf["volume_mm3"] - facts["volume_mm3"]) / facts["volume_mm3"]
            checks.append({"name": "volume", "ok": err <= 0.02,
                           "detail": f"mesh {mf['volume_mm3']:.0f} mm³ vs OpenCASCADE {facts['volume_mm3']:.0f} mm³ "
                                     f"({100 * err:.2f} %)"})
        sm = size_match(extents, dims)
        checks.append({"name": "size", "ok": sm,
                       "detail": (f"{' × '.join(f'{x:.1f}' for x in extents)} mm against the catalog's "
                                  f"{' × '.join(f'{x:g}' for x in dims)} mm" if dims else
                                  "the catalog publishes no size to compare")})
        shutil.copyfile(src, d / f"source{ext}")
        entry = {"component": cid, "origin": origin, "origin_text": ORIGINS[origin], "file": f"{cid}/{cid}.stl",
                 "source_name": name, "source_file": f"{cid}/source{ext}", "source_url": source_url,
                 "sha256": _sha256(data), "imported": now_iso(), "units": units, "scale": scale,
                 "extents_mm": extents, "shift_mm": (shift * 1.0).tolist(),
                 "volume_mm3": float(abs(mesh.volume)) if mf["watertight"] else None,
                 "solids": facts.get("solids"), "faces": mf["faces"], "checks": checks,
                 "ok": all(ch["ok"] is not False for ch in checks), "licence": LICENCE}
        shutil.rmtree(work, ignore_errors=True)
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
