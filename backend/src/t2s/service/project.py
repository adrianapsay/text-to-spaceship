"""Project storage (Addendum 2: any STL file, any time).

Layout of a project folder `data/projects/<name>/`:
  project.json    parts registry (ids, files, hashes, units, user physical edits), settings, counters
  parts/          the STL files exactly as received (never modified)
  inbox/          drop STL files here; they are picked up automatically and need a units confirmation
  cache/          part records (pickled, keyed by file hash + units + pipeline version) and search contexts
  archive.jsonl   validated layouts (one JSON object per line)
"""
from __future__ import annotations

import json
import pickle
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..geometry.stl_io import UNIT_TO_MM, read_stl_bytes
from ..parts.build import DEFAULT_DENSITY, PIPELINE_VERSION, PartRecord, build_part, sha256_bytes, suggest_units

REPO = Path(__file__).resolve().parents[4]
PROJECTS = REPO / "data" / "projects"
DATASET = REPO / "data" / "synthetic"

DEFAULT_SETTINGS = {
    "stage": 1,
    "sliders": {"space": 25, "balance": 25, "inertia": 25, "feasibility": 25, "mass_symmetry": 50, "cable": 0, "cost": 0,
                "speed_quality": 50, "bracket_budget": 50, "optional_parts": 75},
    "target_com_mm": [0.0, 0.0, 0.0],
    "compactness_definition": "one_end",
    "show_frame_mass_in_com": False,
    "part_scale_pct": 100,          # V2: part-size slider (Stage 2), 50 … 100 %
    "form_factor": "3U",            # V2: 3U / 6U / 12U envelope (CDS Rev 14.1)
    "auto_design_brackets": True,   # V2: design the metal-AM / cradle / clamp brackets when the search pauses
    "launch_environment": "gevs",   # V2: launch loads the brackets are designed for (gd.environment)
    "bracket_material": "AlSi10Mg", # V2: AM material of a metal-AM bracket with no material of its own (gd.materials)
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class PartEntry:
    id: str
    name: str
    file: str                       # relative to the project's parts/ folder
    sha256: str
    units: str | None               # None until confirmed (or suggested build pending)
    units_confirmed: bool
    suggested_units: str | None = None
    density_kg_m3: float = DEFAULT_DENSITY
    density_user: bool = False
    mass_override_kg: float | None = None
    locked: bool = False
    lock_pose: dict | None = None
    allowed_override: list[int] | None = None
    tags: list[str] = field(default_factory=list)
    subsystem_override: str | None = None
    added: str = field(default_factory=now_iso)
    source: str = "upload"          # dataset | upload | inbox
    tags_user: bool = False         # tags edited by the user (no automatic suggestion afterwards)


def suggest_tags(name: str, labels: list[str] | None = None, extents=None) -> list[str]:
    """Automatic tag suggestion (editable): circuit boards join the PC/104 stack in Stage 2."""
    low = name.lower()
    if "pcb" in low or "board" in low:
        return ["pcb"]
    if labels and extents is not None and ("thin" in labels) and min(extents) <= 3.0 and sorted(extents)[1] >= 80.0:
        return ["pcb"]
    return []


def _safe_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "part"
    return stem[:80]


def quick_inspect(data: bytes) -> dict:
    """Cheap facts for a file awaiting units: triangle count, raw extents, suggested unit."""
    try:
        tri, fmt = read_stl_bytes(data)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"not a readable STL file ({exc})") from exc
    if len(tri) == 0:
        raise ValueError("not a readable STL file (no triangles found)")
    pts = tri.reshape(-1, 3)
    ext = pts.max(axis=0) - pts.min(axis=0)
    return {"triangles": int(len(tri)), "format": fmt, "raw_extents": ext.tolist(),
            "suggested_units": suggest_units(float(ext.max()))}


def record_cache_key(sha: str, units: str) -> str:
    return f"{sha[:24]}_{units}_v{PIPELINE_VERSION}"


def build_record_file(stl_path: str, cache_path: str, name: str, part_id: str, units: str, confirmed: bool,
                      file_rel: str) -> str:
    """Process-pool job: build one part record and pickle it to the cache. Returns the cache path."""
    import time
    data = Path(stl_path).read_bytes()
    t0 = time.perf_counter()
    rec = build_part(data, name, part_id, units=units, units_confirmed=confirmed, file=file_rel)
    rec.build_s = time.perf_counter() - t0
    tmp = Path(cache_path).with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(rec, protocol=pickle.HIGHEST_PROTOCOL))
    tmp.replace(cache_path)
    return cache_path


class ProjectStore:
    def __init__(self, name: str = "default", root: Path = PROJECTS):
        self.name = name
        self.folder = root / name
        self.parts_dir = self.folder / "parts"
        self.inbox = self.folder / "inbox"
        self.cache = self.folder / "cache"
        self.archive_path = self.folder / "archive.jsonl"
        for d in (self.parts_dir, self.inbox, self.cache):
            d.mkdir(parents=True, exist_ok=True)
        self.entries: dict[str, PartEntry] = {}
        self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.counters = {"part": 0, "layout": 0, "epoch": 0}
        self.revs = {"parts_rev": 0, "constraint_rev": 0, "mass_rev": 0, "weights_rev": 0}
        self.dataset_sha256: str | None = None
        self.load()

    # ------------------------------------------------------------------------------------------ persistence
    def load(self) -> None:
        p = self.folder / "project.json"
        if not p.exists():
            return
        d = json.loads(p.read_text(encoding="utf-8"))
        self.entries = {e["id"]: PartEntry(**e) for e in d.get("parts", [])}
        for e in self.entries.values():          # projects created before tag suggestions existed
            if not e.tags and not e.tags_user:
                e.tags = suggest_tags(e.name)
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        s.update(d.get("settings", {}))
        s["sliders"] = {**DEFAULT_SETTINGS["sliders"], **d.get("settings", {}).get("sliders", {})}
        self.settings = s
        self.counters.update(d.get("counters", {}))
        self.revs.update(d.get("revs", {}))
        self.dataset_sha256 = d.get("dataset_sha256")

    def save(self) -> None:
        d = {"name": self.name, "parts": [asdict(e) for e in self.entries.values()], "settings": self.settings,
             "counters": self.counters, "revs": self.revs, "dataset_sha256": self.dataset_sha256,
             "pipeline_version": PIPELINE_VERSION}
        tmp = self.folder / "project.json.tmp"
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(self.folder / "project.json")

    def next_id(self, kind: str) -> int:
        self.counters[kind] = self.counters.get(kind, 0) + 1
        return self.counters[kind]

    # ------------------------------------------------------------------------------------------ parts
    def seed_from_dataset(self, dataset: Path = DATASET) -> None:
        """First start: the accepted synthetic dataset (mm, confirmed), packable parts only."""
        if self.entries:
            return
        man = json.loads((dataset / "manifest.json").read_text())
        self.dataset_sha256 = man.get("dataset_sha256")
        for p in man["parts"]:
            if p["role"] != "packable":
                continue
            src = dataset / p["file"]
            e = self._add_bytes(src.read_bytes(), src.name, units="mm", confirmed=True, source="dataset")
            e.name = p["name"]
            e.tags = suggest_tags(e.name)
        self.save()

    def _unique_file(self, filename: str) -> str:
        stem = _safe_name(filename)
        cand = f"{stem}.stl"
        k = 2
        while (self.parts_dir / cand).exists():
            cand = f"{stem}_{k}.stl"
            k += 1
        return cand

    def _add_bytes(self, data: bytes, filename: str, units: str | None, confirmed: bool, source: str) -> PartEntry:
        info = quick_inspect(data)          # raises ValueError on a file that is not an STL
        fname = self._unique_file(filename)
        (self.parts_dir / fname).write_bytes(data)
        pid = f"p{self.next_id('part'):02d}"
        e = PartEntry(id=pid, name=_safe_name(filename), file=fname, sha256=sha256_bytes(data),
                      units=units if units else info["suggested_units"], units_confirmed=bool(confirmed and units),
                      suggested_units=info["suggested_units"], source=source, tags=suggest_tags(_safe_name(filename)))
        self.entries[pid] = e
        return e

    def add_file(self, data: bytes, filename: str, units: str | None = None, source: str = "upload") -> PartEntry:
        if units is not None and units not in UNIT_TO_MM:
            raise ValueError(f"unknown units {units!r}; use one of {sorted(UNIT_TO_MM)}")
        e = self._add_bytes(data, filename, units, units is not None, source)
        self.save()
        return e

    def scan_inbox(self) -> list[PartEntry]:
        new = []
        for p in sorted(self.inbox.glob("*")):
            if p.suffix.lower() != ".stl" or not p.is_file():
                continue
            try:
                data = p.read_bytes()
                new.append(self._add_bytes(data, p.name, None, False, "inbox"))
                done = self.inbox / "imported"
                done.mkdir(exist_ok=True)
                shutil.move(str(p), str(done / p.name))
            except (ValueError, OSError) as exc:
                bad = self.inbox / "rejected"
                bad.mkdir(exist_ok=True)
                try:
                    shutil.move(str(p), str(bad / p.name))
                    (bad / (p.name + ".txt")).write_text(str(exc), encoding="utf-8")
                except OSError:
                    pass
        if new:
            self.save()
        return new

    def remove(self, pid: str) -> None:
        self.entries.pop(pid)
        self.save()

    def stl_path(self, e: PartEntry) -> Path:
        return self.parts_dir / e.file

    def cache_path(self, e: PartEntry, units: str | None = None) -> Path:
        return self.cache / f"rec_{record_cache_key(e.sha256, units or e.units)}.pkl"

    def load_record(self, e: PartEntry) -> PartRecord | None:
        p = self.cache_path(e)
        if not p.exists():
            return None
        try:
            rec = pickle.loads(p.read_bytes())
        except Exception:  # noqa: BLE001 - stale or partial cache file: rebuild
            return None
        return self.apply_entry(rec, e)

    @staticmethod
    def apply_entry(rec: PartRecord, e: PartEntry) -> PartRecord:
        """Overlay the registry (identity, units confirmation, user physical edits) on a cached record."""
        rec.id, rec.name, rec.file = e.id, e.name, e.file
        rec.units_confirmed = e.units_confirmed
        if rec.geom_status is None:
            rec.geom_status = rec.status if rec.status != "NEEDS_UNITS" else "VALID"
        if e.units_confirmed:
            rec.status, rec.status_detail = rec.geom_status, rec.geom_detail
        else:
            rec.status = "NEEDS_UNITS"
            rec.status_detail = f"confirm units (suggested: {e.suggested_units}); {rec.geom_detail}".rstrip("; ")
        rec.density_kg_m3 = e.density_kg_m3
        rec.mass_override_kg = e.mass_override_kg
        if rec.geom_status == "WITHHELD":
            rec.mass_source = "USER_MASS" if e.mass_override_kg is not None else "WITHHELD"
        elif e.mass_override_kg is not None:
            rec.mass_source = "USER_MASS"
        elif e.density_user:
            rec.mass_source = "USER_DENSITY"
        else:
            rec.mass_source = "ASSUMED"
        rec.locked, rec.lock_pose = e.locked, e.lock_pose
        rec.tags = list(e.tags)
        if not hasattr(rec, "_all_orients"):
            rec._all_orients = list(rec.allowed_orients)
        base = rec._all_orients
        rec.allowed_orients = [o for o in base if o in e.allowed_override] if e.allowed_override else list(base)
        if not rec.allowed_orients:
            rec.allowed_orients = list(base)
        if e.subsystem_override:
            rec.subsystem = e.subsystem_override
        return rec


def part_json(e: PartEntry, rec: PartRecord | None, quick: dict | None = None, building: bool = False) -> dict:
    """Part object of docs/api-contract.md §2."""
    if rec is None:
        q = quick or {}
        ext = q.get("raw_extents") or [0, 0, 0]
        scale = UNIT_TO_MM.get(e.units or "mm", 1.0)
        return {
            "id": e.id, "name": e.name, "file": e.file, "sha256": e.sha256, "units": e.units or "mm",
            "units_confirmed": e.units_confirmed, "status": "NEEDS_UNITS" if not e.units_confirmed else "ANALYSING",
            "status_detail": (f"confirm units (suggested: {e.suggested_units})" if not e.units_confirmed
                              else "analysing geometry…") + (" — analysing in the background" if building else ""),
            "repairs": [], "triangles": q.get("triangles", 0), "display_triangles": q.get("triangles", 0),
            "subsystem": e.subsystem_override or "unknown", "labels": [],
            "extents_mm": [float(x) * scale for x in sorted(ext, reverse=True)], "volume_mm3": None,
            "density_kg_m3": e.density_kg_m3, "mass_kg": e.mass_override_kg,
            "mass_source": "USER_MASS" if e.mass_override_kg is not None else "ASSUMED",
            "com_canonical_mm": None, "inertia_com_kgm2": None, "principal_kgm2": None, "solidity": None, "obb_fill": None,
            "allowed_orients": list(range(24)), "locked": e.locked, "lock_pose": e.lock_pose, "tags": list(e.tags),
            "pending": True,
        }
    inertia = rec.inertia_com_kgm2()
    principal = np.linalg.eigvalsh(inertia).tolist() if inertia is not None else None
    d = rec.desc or {}
    return {
        "id": rec.id, "name": rec.name, "file": rec.file, "sha256": rec.sha256, "units": rec.units,
        "units_confirmed": rec.units_confirmed, "status": rec.status, "status_detail": rec.status_detail,
        "repairs": list(rec.repairs), "triangles": int(rec.triangles_in), "display_triangles": int(len(rec.f)),
        "subsystem": rec.subsystem, "labels": list(rec.labels), "extents_mm": [float(x) for x in rec.obb_extents_mm],
        "volume_mm3": rec.volume_mm3, "density_kg_m3": rec.density_kg_m3 if rec.has_mass else None,
        "mass_kg": rec.mass_kg, "mass_source": rec.mass_source,
        "com_canonical_mm": rec.com_can_mm.tolist() if rec.com_can_mm is not None else None,
        "inertia_com_kgm2": inertia.tolist() if inertia is not None else None, "principal_kgm2": principal,
        "solidity": d.get("solidity"), "obb_fill": d.get("obb_fill"),
        "allowed_orients": list(rec.allowed_orients), "locked": rec.locked, "lock_pose": rec.lock_pose,
        "tags": list(rec.tags),
        "proxy": {"boxes": int(len(rec.boxes)), "boxes_method": rec.boxes_method, "boxes_certified": rec.boxes_certified,
                  "cover_pieces": len(rec.cover.pieces), "cover_certified": rec.cover.certified,
                  "cover_overhead": (rec.cover.total_hull_volume / rec.volume_mm3 - 1.0)
                  if rec.volume_mm3 and rec.cover.total_hull_volume else None},
        "frame": rec.frame_name, "build_s": rec.build_s,
        "mass_check": rec.ref_check,
    }
