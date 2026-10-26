"""CubeSat Builder designs on disk: data/builder/designs/<id>.json, one file per design (atomic writes), plus each
design's earlier versions in data/builder/designs/<id>.history/<version>.json so a change can be compared or undone.
Builder designs never live inside an optimiser project; Send to Optimization writes a new project of its own."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.fileio import atomic_write_text
from ..service.project import REPO

ROOT = REPO / "data" / "builder"
_ID = re.compile(r"^D-\d{8}-[0-9a-f]{6}$")


class BuilderStore:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.designs = self.root / "designs"
        self.designs.mkdir(parents=True, exist_ok=True)

    def _path(self, did: str) -> Path:
        if not _ID.match(str(did)):
            raise KeyError(did)
        return self.designs / f"{did}.json"

    def save(self, design: dict) -> dict:
        p = self._path(design["id"])
        if p.is_file():                                   # keep the version it replaces
            old = json.loads(p.read_text(encoding="utf-8"))
            h = self.designs / f"{design['id']}.history"
            h.mkdir(exist_ok=True)
            atomic_write_text(h / f"{int(old.get('version', 0)):05d}.json", json.dumps(old, separators=(",", ":")))
        atomic_write_text(p, json.dumps(design, indent=1))
        return design

    def load(self, did: str) -> dict:
        p = self._path(did)
        if not p.is_file():
            raise KeyError(did)
        return json.loads(p.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.designs.glob("D-*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({"id": d["id"], "name": d.get("name"), "updated": d.get("updated"),
                        "version": d.get("version"), "mission_type": (d.get("requirements", {})
                                                                      .get("mission.type") or {}).get("value")})
        return sorted(out, key=lambda x: x.get("updated") or "", reverse=True)

    def versions(self, did: str) -> list[int]:
        h = self.designs / f"{self._path(did).stem}.history"
        return sorted(int(p.stem) for p in h.glob("*.json")) if h.is_dir() else []

    def load_version(self, did: str, version: int) -> dict:
        p = self.designs / f"{self._path(did).stem}.history" / f"{int(version):05d}.json"
        if not p.is_file():
            raise KeyError(f"{did} v{version}")
        return json.loads(p.read_text(encoding="utf-8"))

    def delete(self, did: str) -> None:
        p = self._path(did)
        if not p.is_file():
            raise KeyError(did)
        p.unlink()
