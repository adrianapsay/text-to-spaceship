"""Layout archive with bounded memory (V2: the search runs until Pause, so the archive never stops growing).

* archive.jsonl keeps every archived layout, one JSON object per line. It is append-only: a layout is written when it
  is validated and again when it changes (designed brackets, FINAL); the last line of an id wins. LayoutArchive
  indexes the byte offset of that line, so a layout that is not in memory ("cold") is read back when it is asked
  for. The coordinator keeps in memory only the layouts it needs ("hot", Coordinator._enforce_memory).
* ObjectiveTable keeps one small row per layout of the current inputs — cv and the raw objectives — which is all that
  the choice of the best layout, the normaliser, the candidate filter and the Pareto plot need: a cold layout still
  counts without being read.
* ParetoFront is the incremental non-dominated filter: O(front) per new point instead of the O(N²) pairwise
  comparison (two N × N × 3 boolean arrays, about 170 MB each at 7,500 layouts).
* Compaction rewrites the file with only the last line of every id (Coordinator._load_archive: at start, when many
  lines are superseded).
"""
from __future__ import annotations

import itertools
import json
import math
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

import numpy as np

OBJECTIVES = ("L", "D", "T", "P", "G", "H", "C", "O")     # raw objectives, all minimised (optimise/scalarize.py)
OK_STATUSES = ("VALIDATED", "FINAL")

# The start of every line LayoutEntry.to_store() writes (dataclass field order) and its spec_sig, which comes just
# before "meta": read without parsing the whole line (a Stage 2 layout is about 40 kB of JSON). A line that does not
# match is parsed in full.
_HEAD = re.compile(rb'\{"id": "([^"\\]*)", "hash": "([^"\\]*)", "stage": (\d+), "mode": "(?:[^"\\]|\\.)*", '
                   rb'"status": "([^"\\]*)", "parts_sig": "([^"\\]*)", ')
_SPEC = re.compile(rb'"spec_sig": "([^"\\]*)", "meta": ')


class Line(NamedTuple):
    """Where the last line of a layout is in archive.jsonl, and what the index needs without reading it."""
    off: int
    size: int
    stage: int
    parts_sig: str
    spec_sig: str
    status: str
    hash: str


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class LayoutArchive:
    """Every archived layout by id, in memory ("hot") or only in archive.jsonl ("cold", read back on access).

    Dict-like for the coordinator and the API: archive[id], .get(id), `id in archive`, len() and iteration cover every
    layout; .values() and .items() only the layouts in memory (reading every cold layout would defeat the purpose).
    A layout read back on request stays in memory among the RECENT last ones; on_load (the coordinator's re-scoring
    for the current inputs) runs on every layout read back."""

    RECENT = 32

    def __init__(self, path: Path, decode: Callable[[dict], object], on_load: Callable[[object], None] | None = None):
        self.path = Path(path)
        self.decode = decode
        self.on_load = on_load
        self._hot: dict = {}
        self._lines: dict[str, Line] = {}
        self._recent: OrderedDict = OrderedDict()
        self._strs: dict[str, str] = {}
        self._lock = threading.RLock()
        self._needs_newline = False
        self.superseded = 0                   # lines of the file that a later line of the same id replaces
        self.loads = 0                        # layouts read back from the file

    # ------------------------------------------------------------------------------------------ file
    def scan(self, by_hash: dict | None = None) -> None:
        """Index the file: offset and length of the last line of every id (by_hash gets every layout's hash)."""
        with self._lock:
            self._lines, self._hot, self._recent = {}, {}, OrderedDict()
            self.superseded = 0
            self._needs_newline = False
            if not self.path.exists():
                return
            off = 0
            with open(self.path, "rb") as fh:
                for raw in fh:
                    n = len(raw)
                    rec = self._head(raw, off, n)
                    off += n
                    self._needs_newline = not raw.endswith(b"\n")
                    if rec is None:
                        continue
                    if rec[0] in self._lines:
                        self.superseded += 1
                    self._lines[rec[0]] = rec[1]
                    if by_hash is not None:
                        by_hash[rec[1].hash] = rec[0]

    def _s(self, s: str) -> str:
        return self._strs.setdefault(s, s)    # the same few signatures on thousands of lines: one string each

    def _head(self, raw: bytes, off: int, n: int) -> tuple[str, Line] | None:
        m = _HEAD.match(raw)
        s = _SPEC.search(raw, m.end()) if m else None
        if m and s:
            lid, h, stage, status, psig = (m.group(1).decode(), m.group(2).decode(), int(m.group(3)),
                                           m.group(4).decode(), m.group(5).decode())
            ssig = s.group(1).decode()
        else:
            if not raw.strip():
                return None
            try:
                d = json.loads(raw)
            except ValueError:
                return None                   # e.g. a line cut short when the process was killed
            if not isinstance(d, dict) or not isinstance(d.get("id"), str):
                return None
            lid, h, stage = d["id"], str(d.get("hash", "")), int(d.get("stage") or 0)
            status, psig, ssig = str(d.get("status", "")), str(d.get("parts_sig", "")), str(d.get("spec_sig", ""))
        return lid, Line(off, n, stage, self._s(psig), self._s(ssig), self._s(status), h)

    def append(self, e) -> None:
        """Write a layout as a new last line (it wins over its earlier lines) and keep it in memory."""
        data = (json.dumps(e.to_store()) + "\n").encode("utf-8")
        with self._lock:
            with open(self.path, "ab") as fh:
                fh.seek(0, os.SEEK_END)
                if self._needs_newline and fh.tell():
                    fh.write(b"\n")           # never glue a line to one cut short
                off = fh.tell()
                fh.write(data)
            self._needs_newline = False
            if e.id in self._lines:
                self.superseded += 1
            self._lines[e.id] = Line(off, len(data), int(e.stage), self._s(e.parts_sig), self._s(e.spec_sig),
                                     self._s(e.status), e.hash)
            self._hot[e.id] = e

    def rewrite(self, keep: Callable[[str, str], bool] | None = None) -> int:
        """Rewrite the file with one line per id: the last line, or the layout as it is in memory. keep(id, status)
        chooses the layouts to keep (default all: compaction). Returns the number of lines that went."""
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            before = len(self._lines) + self.superseded
            ids = list(self._lines) + [k for k in self._hot if k not in self._lines]
            new: dict[str, Line] = {}
            self.path.touch()
            with open(tmp, "wb") as out, open(self.path, "rb") as src:
                for lid in ids:
                    e = self._hot.get(lid)
                    old = self._lines.get(lid)
                    status = e.status if e is not None else old.status
                    if keep is not None and not keep(lid, status):
                        continue
                    if e is not None:
                        data = (json.dumps(e.to_store()) + "\n").encode("utf-8")
                        stage, psig, ssig, h = int(e.stage), e.parts_sig, e.spec_sig, e.hash
                    else:
                        src.seek(old.off)
                        data = src.read(old.size)
                        if not data.endswith(b"\n"):
                            data += b"\n"
                        stage, psig, ssig, h = old.stage, old.parts_sig, old.spec_sig, old.hash
                    new[lid] = Line(out.tell(), len(data), stage, self._s(psig), self._s(ssig), self._s(status), h)
                    out.write(data)
            tmp.replace(self.path)
            self._lines = new
            for lid in [k for k in self._hot if k not in new]:
                del self._hot[lid]
                self._recent.pop(lid, None)
            self.superseded = 0
            self._needs_newline = False
            return before - len(new)

    def should_compact(self, min_superseded: int = 200, share: float = 0.2) -> bool:
        """Many lines superseded by later lines of the same id (designed brackets, FINAL): worth a rewrite."""
        total = len(self._lines) + self.superseded
        return self.superseded >= min_superseded and self.superseded >= share * total

    def _decode(self, lid: str, raw: bytes):
        try:
            return self.decode(json.loads(raw))
        except Exception:  # noqa: BLE001 - a line of another format: skipped, as when the archive was read whole
            self._lines.pop(lid, None)
            return None

    def _read(self, lid: str):
        line = self._lines.get(lid)
        if line is None:
            return None
        with open(self.path, "rb") as fh:
            fh.seek(line.off)
            raw = fh.read(line.size)
        return self._decode(lid, raw)

    def read_many(self, ids: Iterable[str]) -> Iterator[tuple[str, object]]:
        """(id, layout) for ids not in memory, read in file order through one file handle; the layouts are not kept
        and on_load does not run (the caller re-scores them)."""
        with self._lock:
            want = sorted((self._lines[i].off, i) for i in ids if i in self._lines and i not in self._hot)
            if not want:
                return
            with open(self.path, "rb") as fh:
                for off, lid in want:
                    line = self._lines.get(lid)
                    if line is None:
                        continue
                    fh.seek(off)
                    e = self._decode(lid, fh.read(line.size))
                    if e is not None:
                        self.loads += 1
                        yield lid, e

    # ------------------------------------------------------------------------------------------ dict-like
    def __contains__(self, lid) -> bool:
        return lid in self._hot or lid in self._lines

    def __len__(self) -> int:
        return len(self._lines) + sum(1 for k in self._hot if k not in self._lines)

    def __iter__(self) -> Iterator[str]:
        ids = list(self._lines)
        ids += [k for k in self._hot if k not in self._lines]
        return iter(ids)

    def keys(self) -> list[str]:
        return list(self)

    def values(self) -> list:
        return list(self._hot.values())

    def items(self) -> list:
        return list(self._hot.items())

    def __setitem__(self, lid: str, e) -> None:
        self._hot[lid] = e

    def __getitem__(self, lid: str):
        e = self.get(lid)
        if e is None:
            raise KeyError(lid)
        return e

    def get(self, lid, default=None):
        e = self._hot.get(lid)
        if e is not None:
            return e
        if not isinstance(lid, str) or lid not in self._lines:
            return default
        e = self.load(lid)
        return default if e is None else e

    def load(self, lid: str, keep: bool = True):
        """The layout, read back from the file if it is not in memory (kept among the recent ones unless keep=False)."""
        with self._lock:
            e = self._hot.get(lid)
            if e is not None:
                return e
            e = self._read(lid)
            if e is None:
                return None
            self.loads += 1
            if keep:
                self._hot[lid] = e
                self._recent[lid] = True
                while len(self._recent) > self.RECENT:
                    self._recent.popitem(last=False)
        if self.on_load is not None:
            self.on_load(e)
        return e

    # ------------------------------------------------------------------------------------------ memory
    def evict(self, lid: str) -> bool:
        """Drop a layout from memory; only one the file has (an id never written stays)."""
        with self._lock:
            if lid not in self._lines or lid not in self._hot:
                return False
            del self._hot[lid]
            self._recent.pop(lid, None)
            return True

    @property
    def n_hot(self) -> int:
        return len(self._hot)

    def hot_ids(self) -> list[str]:
        return list(self._hot)

    def is_hot(self, lid: str) -> bool:
        return lid in self._hot

    def recent_ids(self) -> list[str]:
        return list(self._recent)

    def newest_ids(self, n: int) -> list[str]:
        """The last n ids written for the first time (layout ids only grow: the newest layouts)."""
        return list(itertools.islice(reversed(self._lines), n))

    def line(self, lid: str) -> Line | None:
        return self._lines.get(lid)

    def status_of(self, lid: str) -> str | None:
        e = self._hot.get(lid)
        if e is not None:
            return e.status
        line = self._lines.get(lid)
        return line.status if line is not None else None

    def note_status(self, lid: str, status: str) -> None:
        """A layout's status after re-scoring (the COM-box verdict follows the masses): status_of stays right for a
        layout that goes back to the file only."""
        line = self._lines.get(lid)
        if line is not None and line.status != status:
            self._lines[lid] = line._replace(status=self._s(status))

    def ids_of(self, stage: int, parts_sig: str, spec_sig: str | None = None) -> list[str]:
        """Ids of the layouts found for these inputs (stage, parts and, when given, validation rules)."""
        out = [lid for lid, x in self._lines.items() if x.stage == stage and x.parts_sig == parts_sig
               and (spec_sig is None or x.spec_sig == spec_sig)]
        out += [lid for lid, e in self._hot.items() if lid not in self._lines and e.stage == stage
                and e.parts_sig == parts_sig and (spec_sig is None or e.spec_sig == spec_sig)]
        return out

    def hashes(self) -> dict[str, str]:
        """hash -> id of every layout (for Coordinator.by_hash after a rewrite)."""
        out = {x.hash: lid for lid, x in self._lines.items()}
        out.update({e.hash: lid for lid, e in self._hot.items() if lid not in self._lines})
        return out


class _Rows:
    """Rows of one group of an ObjectiveTable: ids and a matrix [cv, objective values …]."""

    def __init__(self, width: int):
        self.ids: list[str] = []
        self.m = np.empty((64, width))
        self.n = 0

    def append(self, lid: str, vec) -> None:
        if self.n == len(self.m):
            self.m = np.vstack([self.m, np.empty_like(self.m)])
        self.m[self.n] = vec
        self.ids.append(lid)
        self.n += 1

    def remove(self, lid: str) -> None:
        i = self.ids.index(lid)
        self.m[i:self.n - 1] = self.m[i + 1:self.n]
        del self.ids[i]
        self.n -= 1


class ObjectiveTable:
    """One row per layout of one search context: its class ("ok" = VALIDATED or FINAL, "inf" = INFEASIBLE), cv and its
    finite raw objectives, grouped by which objectives a layout has (one group in practice). Layouts of other
    statuses (REJECTED) are only counted. A few floats per layout, so every layout of the current inputs counts in
    the choices made from it, in memory or not."""

    _uids = itertools.count(1)

    def __init__(self, key=None):
        self.key = key                      # the inputs the rows were computed for (Coordinator._table_key)
        self.uid = next(self._uids)
        self.fam_ver = 0                    # Coordinator._fam_ver of these layouts when the rows were last right
        self.groups: dict[tuple, _Rows] = {}
        self._where: dict[str, tuple] = {}
        self._other: set[str] = set()
        self.changes = 0                    # rows replaced or removed (rows added do not count)

    def __len__(self) -> int:
        return len(self._where) + len(self._other)

    def __contains__(self, lid) -> bool:
        return lid in self._where or lid in self._other

    def count(self, cls: str) -> int:
        return sum(r.n for (c, _), r in self.groups.items() if c == cls)

    def put(self, lid: str, status: str, cv: float, raw: dict) -> bool:
        """Add or replace a layout's row; True when an earlier row of it was replaced."""
        replaced = self.discard(lid)
        cls = "ok" if status in OK_STATUSES else "inf" if status == "INFEASIBLE" else None
        if cls is None:
            self._other.add(lid)
            return replaced
        keys = tuple(k for k in OBJECTIVES if _finite(raw.get(k)))
        rows = self.groups.get((cls, keys))
        if rows is None:
            rows = self.groups[(cls, keys)] = _Rows(len(keys) + 1)
        rows.append(lid, [float(cv), *(float(raw[k]) for k in keys)])
        self._where[lid] = (cls, keys)
        return replaced

    def discard(self, lid: str) -> bool:
        if lid in self._other:
            self._other.discard(lid)
            self.changes += 1
            return True
        g = self._where.pop(lid, None)
        if g is None:
            return False
        self.groups[g].remove(lid)
        self.changes += 1
        return True

    def blocks(self, cls: str) -> Iterator[tuple[tuple, list[str], np.ndarray]]:
        """(objective keys, ids, rows [cv, values …]) of every group of a class."""
        for (c, keys), r in self.groups.items():
            if c == cls and r.n:
                yield keys, r.ids, r.m[:r.n]

    def dominated(self, raw: dict, keys: tuple) -> bool:
        """True when an "ok" layout is at least as good as raw in every one of keys and better in one
        (optimise.scalarize.dominates over the layouts that have all of keys)."""
        v = np.array([raw[k] for k in keys], float)
        for gk, _, m in self.blocks("ok"):
            if not set(keys) <= set(gk):
                continue
            f = m[:, [1 + gk.index(k) for k in keys]]
            if np.any(np.all(f <= v, axis=1) & np.any(f < v, axis=1)):
                return True
        return False

    def extremes(self, need: str = "D") -> tuple[dict, dict, int]:
        """Smallest and largest value of every objective over the "ok" layouts that have `need`, and how many there
        are: what Normaliser.update_from takes from them."""
        lo: dict[str, float] = {}
        hi: dict[str, float] = {}
        n = 0
        for gk, _, m in self.blocks("ok"):
            if need not in gk:
                continue
            n += len(m)
            for j, k in enumerate(gk):
                col = m[:, 1 + j]
                lo[k] = min(lo.get(k, math.inf), float(col.min()))
                hi[k] = max(hi.get(k, -math.inf), float(col.max()))
        return lo, hi, n


class ParetoFront:
    """Incremental non-dominated set of points (all coordinates minimised). insert() compares a new point with the
    front only — O(front · dim) — and removes the points it dominates; a point equal to a front point is kept too
    (neither dominates the other), so the result is the same set as the pairwise comparison of all points."""

    def __init__(self, dim: int):
        self.dim = dim
        self.ids: list = []
        self._v = np.empty((32, dim))

    def __len__(self) -> int:
        return len(self.ids)

    def values(self) -> np.ndarray:
        return self._v[:len(self.ids)]

    def dominated(self, v) -> bool:
        f = self.values()
        v = np.asarray(v, float)
        return bool(len(f)) and bool(np.any(np.all(f <= v, axis=1) & np.any(f < v, axis=1)))

    def insert(self, key, v) -> tuple[bool, list]:
        """Add a point unless a front point dominates it; returns (added, keys of the points it removed)."""
        v = np.asarray(v, float)
        n = len(self.ids)
        f = self._v[:n]
        if n and np.any(np.all(f <= v, axis=1) & np.any(f < v, axis=1)):
            return False, []
        removed = []
        if n:
            gone = np.all(v <= f, axis=1) & np.any(v < f, axis=1)
            if gone.any():
                keep = ~gone
                removed = [k for k, g in zip(self.ids, gone) if g]
                self.ids = [k for k, g in zip(self.ids, gone) if not g]
                self._v[:len(self.ids)] = f[keep]
                n = len(self.ids)
        if n == len(self._v):
            self._v = np.vstack([self._v, np.empty_like(self._v)])
        self._v[n] = v
        self.ids.append(key)
        return True, removed
