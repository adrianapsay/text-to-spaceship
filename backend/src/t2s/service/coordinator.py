"""Coordinator: the single writer of optimisation state (protocol §H.2, §M; api-contract §4).

* Parts, settings and revisions live here; workers never decide anything.
* Search islands run in short time slices with the current weights; their candidates are re-scored here with the
  current masses and weights, and only the validator may promote a layout to VALIDATED.
* Every validated layout goes to the archive. A slider move re-scores the archive at once (no new geometry), a
  mass edit recomputes the physics terms of archived layouts at once, so the best validated layout for the current
  inputs is always available without waiting for the search.
* A layout belongs to the inputs it was validated for: its parts signature (ids, file hashes, units) and its
  constraint signature (stage, locks, allowed orientations, tags). When the current inputs return to those
  signatures, the layout is current again and is re-stamped with the current revisions.
* V2: the search runs until the user presses Pause (no automatic stop). Memory stays bounded however long it runs:
  every layout stays in archive.jsonl, only some stay in memory, and the choices over all layouts of the current
  inputs use one small row of objective values per layout (service/archive.py, _enforce_memory).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import multiprocessing as mp
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..bench.convergence_table import recommended_minimum
from ..collision.geom import part_geom_from_record, to_world
from ..collision.validate import Validator
from ..constraints import stage2 as s2
from ..core import formfactor
from ..core.fileio import atomic_write_text
from ..core.rotations import ROTATIONS_F, as_lists
from ..geometry.stl_io import UNIT_TO_MM, read_stl_bytes
from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO
from ..optimise.brkga import Evaluator
from ..optimise.scalarize import RHO, Normaliser, alpha_from, scalarise, slider_weights
from ..optimise.selector import ALGORITHMS, AlgorithmChoice, grid_map, part_stats, select_algorithm, sweep
from ..physics.assembly import PartPhys, assembly, com_box_check, inertia_metrics
from .archive import OK_STATUSES, LayoutArchive, ObjectiveTable, ParetoFront
from .context import SearchContext, build_context, packable, parts_signature, stage2_config, write_context
from .project import PartEntry, ProjectStore, build_record_file, now_iso, part_json, quick_inspect

VERSION = "2.0.0-dev"
ALGORITHM = {"id": "hybrid_box", "label": "Hybrid BRKGA + box decoder", "reason": "archived layout"}
SEARCH_LABELS = {"brkga": "BRKGA + memetic local search", "lahc": "late-acceptance hill climbing",
                 "nsga2": "NSGA-II (pymoo)"}
DECODER_LABELS = {"box": "box decoder", "heightmap": "height-map decoder"}
AM_LEVEL_TEXT = {0: "simple brackets only", 1: "metal AM only where no simple bracket fits",
                 2: "metal AM where it costs at most 2x the simple bracket",
                 3: "metal AM where it costs at most 10x the simple bracket", 4: "metal AM wherever it fits"}
SELECTOR_SETTLE_S = 1.0
SETTINGS_SETTLE_S = 1.5      # V2: the automatic bracket design / STL save waits until a slider has stopped moving
SLIDER_LABELS = {"space": "Use Space Efficiently", "balance": "Balance the Spacecraft",
                 "inertia": "Reduce Rotational Inertia", "feasibility": "Improve Physical Feasibility",
                 "cable": "Keep cable path clear", "cost": "Keep hardware cost low", "bracket_budget": "Bracket budget",
                 "optional_parts": "Include optional parts", "mass_symmetry": "Mass-distribution symmetry",
                 "speed_quality": "Computation: speed / quality"}
SETTING_LABELS = {"form_factor": "CubeSat size", "stage": "Stage", "part_scale_pct": "Part size",
                  "target_com_mm": "COM target", "compactness_definition": "Compactness definition"}
# Sliders that do not change what a search finds. speed_quality only ever set how long the search waited without
# improvement before it stopped itself; the search now runs until Pause, so it changes nothing (the selector and the
# workers never read it) and moving it keeps the saved bracket STL files.
NOT_SEARCH_SLIDERS = ("speed_quality",)
REV_KEYS = ("parts_rev", "constraint_rev", "mass_rev", "weights_rev")


class InvalidSetting(ValueError):
    """A request's value is unknown or out of range (the API answers 400; other ValueErrors are conflicts, 409)."""


def settings_change_text(before: dict, after: dict) -> str:
    """What moved between two Coordinator._settings_view() results, e.g. "Balance the Spacecraft 36 → 40"."""
    def val(x):
        return f"{x:g}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)
    out = [f"{SLIDER_LABELS.get(k, k)} {val((before.get('sliders') or {}).get(k))} → {val(v)}"
           for k, v in (after.get("sliders") or {}).items() if (before.get("sliders") or {}).get(k) != v]
    out += [f"{label} {val(before.get(k))} → {val(after.get(k))}" for k, label in SETTING_LABELS.items()
            if before.get(k) != after.get(k)]
    return ", ".join(out) or "settings changed"


def _kill_tree(pid: int | None) -> None:
    """Terminate a study process and the worker processes it spawned (they are its children)."""
    if not pid:
        return
    try:
        import psutil
        p = psutil.Process(pid)
        for c in p.children(recursive=True):
            c.kill()
        p.kill()
    except Exception:  # noqa: BLE001 - already gone
        pass


def _bench_main(out_dir: str, opts: dict) -> None:
    """Background benchmark process (protocol §J.3) on the accepted dataset."""
    import json as _json
    from ..bench.instances import dataset_instances
    from ..bench.runner import PRESET_IDS, run_benchmarks
    from ..parts.build import build_part
    repo = Path(__file__).resolve().parents[4]
    man = _json.loads((repo / "data" / "synthetic" / "manifest.json").read_text())
    recs = {p["name"]: build_part((repo / "data" / "synthetic" / p["file"]).read_bytes(), p["name"], p["name"],
                                  file=p["file"]) for p in man["parts"] if p["role"] == "packable"}
    want = set(opts.get("instances", ["I1", "I2", "I3", "I4", "I5"]))
    insts = [i for i in dataset_instances(recs) if i.id in want]
    prog = Path(out_dir) / "progress.json"

    def progress(frac, r):
        atomic_write_text(prog, _json.dumps({"status": "RUNNING", "progress": frac}))
    run_benchmarks(insts, Path(out_dir), budget=float(opts.get("budget", 5000)), seeds=int(opts.get("seeds", 10)),
                   workers=int(opts.get("workers", 4)), presets=tuple(opts.get("presets", PRESET_IDS)), progress=progress)
    atomic_write_text(prog, _json.dumps({"status": "DONE", "progress": 1.0}))


def _mode_name(meta: dict | None) -> str:
    return "continuous_cable" if (meta or {}).get("mode") == "continuous" else "default"


def perturbed_weights(weights: dict, k: int, sigma: float = 0.3) -> dict:
    """Island k searches slightly perturbed weights (protocol §F.7) so nearby slider positions are already covered
    in the archive; island 0 uses the exact weights. Deterministic per island; all candidates are re-scored with
    the exact weights in the coordinator."""
    if k == 0:
        return dict(weights)
    rng = np.random.default_rng(1000 + k)
    keys = sorted(weights)
    f = np.exp(sigma * rng.standard_normal(len(keys)))
    w = np.array([weights[x] for x in keys]) * f
    w /= w.sum()
    return {x: float(v) for x, v in zip(keys, w)}


def island_plans(choice: AlgorithmChoice, n: int) -> list[dict]:
    """Which search runs on which decoder in each island, for the selected algorithm."""
    plans = []
    if choice.id == "nsga2_box":                 # benchmark evidence favours NSGA-II: most islands run it
        plans = [{"search": "nsga2", "decoder": "box", "h": 2.0} for _ in range(n)]
        if n >= 3:
            plans[0] = {"search": "brkga", "decoder": "box", "h": 2.0}
        if n >= 2:
            plans[-1] = {"search": "lahc", "decoder": "box", "h": 2.0}
        plans[0]["all_seeds"] = True
        return plans
    for i in range(n):
        dec = choice.decoder if choice.decoder != "mixed" else ("box" if i % 2 == 0 else "heightmap")
        plans.append({"search": "brkga", "decoder": dec, "h": 2.0})
    if n >= 2:
        plans[-1]["search"] = "lahc"
    if n >= 4:
        plans[-2] = {"search": "nsga2", "decoder": "heightmap" if choice.decoder == "heightmap" else "box", "h": 2.0}
    if plans:
        plans[0]["all_seeds"] = True
    return plans
POP_SIZE = 60
SLICE_S = 0.5
PROGRESS_EVERY_S = 0.5
CANDIDATE_EVERY_S = 0.25
# Bounded memory (_enforce_memory): layouts kept in memory beyond the pinned ones (best, least-violating, FINAL, a
# bracket design or STL save under way, the last ones read on request)
TOP_K = 500                 # the best-scoring layouts of the current inputs
NEWEST_KEEP = 200           # the newest layouts (the layout lists show the newest 200)
HOT_SLACK = 100             # eviction runs once this many more are in memory
MEMORY_CHECK_S = 5.0
TABLE_CACHE = 4             # objective tables of recently searched inputs kept for a return to them


def _layout_order(lid: str) -> tuple:
    """Sort key of layout ids by number ("L-10000" after "L-9999"; a plain string sort puts it before)."""
    num = lid[2:] if lid.startswith("L-") else ""
    return (1, int(num), lid) if num.isdigit() else (0, 0, lid)


def _f(x):
    """JSON-safe float (NaN/inf -> None)."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return _f(o)
    return o


def layout_hash(stage: int, poses) -> str:
    items = sorted((pid, int(o), [int(round(v * 1000)) for v in t]) for pid, o, t in poses)
    return hashlib.sha256(json.dumps([stage, items]).encode()).hexdigest()[:16]


@dataclass
class LayoutEntry:
    id: str
    hash: str
    stage: int
    mode: str
    status: str
    parts_sig: str
    constraint_sig: str
    poses: list                          # [(part_id, orient, t_mm ndarray)] — t is an exact multiple of 1 µm
    geo: dict                            # geometry-only metrics (length, span, clearance …)
    validation: dict
    origin: str = "search"
    created: str = field(default_factory=now_iso)
    revs: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    g: float = math.inf
    normalised: dict = field(default_factory=dict)
    norm_epoch: int = 0
    cv: float = 0.0
    keys: list | None = None
    algorithm: dict = field(default_factory=lambda: dict(ALGORITHM))
    spec_sig: str = ""
    meta: dict = field(default_factory=dict)     # Stage 2: stack, corridor, mounts, standoffs, overflow
    part_scale: float = 1.0                      # V2 part-size factor the layout was found and validated at

    def to_store(self) -> dict:
        d = asdict(self)
        d["poses"] = [[pid, int(o), [int(round(v * 1000)) for v in t]] for pid, o, t in self.poses]
        return jsonable(d)

    @staticmethod
    def from_store(d: dict) -> "LayoutEntry":
        d = dict(d)
        d["poses"] = [(pid, int(o), np.asarray(t, float) / 1000.0) for pid, o, t in d["poses"]]
        d["g"] = d.get("g") if d.get("g") is not None else math.inf
        return LayoutEntry(**d)


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.seq = 0
        self.applied = 0
        self.want_candidates = False


class WorkerHandle:
    def __init__(self, wid: int, role: str, proc, cmd_q):
        self.id, self.role, self.proc, self.cmd_q = wid, role, proc, cmd_q
        self.ready = False
        self.ctx_id: str | None = None
        self.ctx_sent: tuple | None = None
        self.busy = False
        self.job: int | None = None
        self.evaluations = 0
        self.generations = 0
        self.best_g: float | None = None
        self.plan: dict = {}
        self.info: dict = {}


class Coordinator:
    def __init__(self, store: ProjectStore, n_islands: int | None = None, n_validators: int = 2,
                 auto_start: bool = True, seed: int = 20261021, workers: bool = True):
        self.store = store
        cpu = os.cpu_count() or 4
        self.n_islands = n_islands if n_islands is not None else max(1, min(6, cpu - 4))
        self.n_validators = n_validators
        self.auto_start = auto_start
        self.seed = seed
        self.use_workers = workers
        self.records: dict = {}
        self.geoms: dict = {}
        self.quick: dict[str, dict] = {}
        self.build_errors: dict[str, str] = {}
        self.builds: dict[tuple[str, str], asyncio.Future] = {}
        self.archive = LayoutArchive(store.archive_path, LayoutEntry.from_store, on_load=self._hydrate)
        self.by_hash: dict[str, str] = {}
        self.norms: dict[str, Normaliser] = {}
        self.raw_pool: dict[str, list] = {}
        self.ctx: SearchContext | None = None
        self.ctx_path: Path | None = None
        self.ctx_counter = 0
        self.ev: Evaluator | None = None
        self.run_status = "IDLE"
        self.status_detail = ""
        self.clients: set[Client] = set()
        self.workers: list[WorkerHandle] = []
        self.res_q = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.job_counter = 0
        self.val_queue: list[tuple] = []           # (g, hash, poses, raw, keys, ctx_id, sigs)
        self.val_pending: dict[int, tuple] = {}
        self.pending_hashes: set[str] = set()
        self.best_id: str | None = None
        self.best_g_hist: list[tuple[float, float]] = []
        self._searched: dict[str | None, float] = {}   # search context -> seconds spent SEARCHING (closed spells)
        self._search_since: float | None = None        # start of the current SEARCHING spell
        self._search_ctx: str | None = None            # the search context that spell counts for
        self._table: ObjectiveTable | None = None      # one row per layout of the current inputs (archive.py)
        self._tables: OrderedDict = OrderedDict()      # tables of recently searched inputs, for a return to them
        self._fam_ver: dict[tuple, int] = {}           # (stage, parts_sig, spec_sig) -> changes to its layouts
        self._dfront: dict | None = None               # the Pareto plot's front (pareto, _display_front)
        self._design_lid: str | None = None            # layout of the bracket design run under way
        self.last_memory = 0.0
        self.evaluations = 0
        self.last_progress = 0.0
        self.last_candidate = 0.0
        self.last_inject = 0.0
        self.last_norm_check = 0.0
        self.last_inbox = 0.0
        self.candidate: dict | None = None
        self.proof_cache: dict[tuple, dict] = {}
        self.build_pool: ProcessPoolExecutor | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self.ready = False
        self.errors: list[str] = []
        self._qual: dict[tuple[str, str], bool] = {}
        self.last_pareto = 0.0
        self.search_requested = False
        self.choice: AlgorithmChoice | None = None
        self.choice_pending: tuple[AlgorithmChoice, float] | None = None
        self.least_id: str | None = None           # Stage 2: least-violating certified candidate
        self.selector_log: list[dict] = []
        self._stats = None
        self._stats_sig = None
        self.ladder_pool: ProcessPoolExecutor | None = None
        self.ladders: dict[str, dict] = {}         # part_id -> {future, path, mtime, status}
        self.reps: dict[str, dict] = {}            # part_id -> {algorithm: Representation} (chosen levels)
        self.last_ladder_poll = 0.0
        self.auto_ladder = True
        self.ladder_opts: dict = {}
        self.attribution_opts: dict = {}
        self.cpsat_pool: ProcessPoolExecutor | None = None
        self.cpsat_time_s = 60.0
        self.cpsat_results: dict[str, dict] = {}     # parts_sig -> {status, length_mm, lower_bound_mm, ...}
        self.use_cpsat = True
        self.evidence: list[dict] = []               # benchmark evidence rows for the selector (M8)
        self.evidence_source: str | None = None
        self.studies: dict[str, dict] = {}           # "size" | "benchmark" -> {proc, path, mtime}
        self.mfg_budget_s = 90.0
        self._scaled: dict = {}                      # (part, record, scale, mass inputs) -> [scaled record, geometry]
        self._sig_scale: dict[str, float] = {}       # parts signature -> part-size factor of that context

    # =========================================================================================== lifecycle
    @property
    def revs(self) -> dict:
        return {"epoch": self.store.counters["epoch"], **self.store.revs}

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.store.counters["epoch"] = self.store.counters.get("epoch", 0) + 1
        self.store.seed_from_dataset()
        self.store.save()
        self._load_archive()
        self._load_evidence()
        for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
            os.environ[var] = "1"
        spawn = mp.get_context("spawn")
        self.build_pool = ProcessPoolExecutor(max_workers=2, mp_context=spawn)
        self.ladder_pool = ProcessPoolExecutor(max_workers=1, mp_context=spawn)
        self.cpsat_pool = ProcessPoolExecutor(max_workers=1, mp_context=spawn)
        for e in self.store.entries.values():
            self._load_ladder(e)
        if self.use_workers:
            self.res_q = spawn.Queue()
            from .worker import island_main
            roles = ["island"] * self.n_islands + ["validator"] * self.n_validators
            for wid, role in enumerate(roles):
                q = spawn.Queue()
                p = spawn.Process(target=island_main, args=(wid, role, q, self.res_q, self.seed), daemon=True)
                p.start()
                self.workers.append(WorkerHandle(wid, role, p, q))
            threading.Thread(target=self._pump, daemon=True).start()
        # part records: cache hits load at once, the rest build in the background
        for e in list(self.store.entries.values()):
            rec = self.store.load_record(e)
            if rec is not None:
                self._set_record(rec)
            else:
                self._start_build(e, e.units)
        self._refresh_inputs("start", bump_parts=False)
        self.ready = True
        if self.auto_start and self.ctx is not None:
            self._set_status("SEARCHING", "searching")
        self._tasks.append(asyncio.create_task(self._ticker()))

    async def stop(self) -> None:
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        for name in list(self.studies):
            self.stop_study(name)
            s = self.studies[name]
            _kill_tree(s["proc"].pid)
        for w in self.workers:
            try:
                w.cmd_q.put(("stop",))
            except Exception:  # noqa: BLE001
                pass
        for w in self.workers:
            w.proc.join(timeout=3)
            if w.proc.is_alive():
                w.proc.terminate()
        if self.res_q is not None:
            try:
                self.res_q.put(("shutdown",))
            except Exception:  # noqa: BLE001
                pass
        if self.build_pool:
            self.build_pool.shutdown(wait=False, cancel_futures=True)
        if self.__dict__.get("_stl_io") is not None:
            self._stl_io.shutdown(wait=True)        # saved STL files: short writes, never left half-done
        for pool in (self.ladder_pool, self.cpsat_pool):
            if not pool:
                continue
            procs = list((getattr(pool, "_processes", None) or {}).values())
            pool.shutdown(wait=False, cancel_futures=True)
            for p in procs:                     # a ladder or CP-SAT run can take minutes: do not wait for it
                try:
                    p.terminate()
                except Exception:  # noqa: BLE001
                    pass
        self.store.save()

    def _pump(self) -> None:
        while True:
            try:
                msg = self.res_q.get()
            except (EOFError, OSError):
                return
            if msg[0] == "shutdown" or self._stopping:
                return
            if self.loop is not None:
                self.loop.call_soon_threadsafe(self._on_worker_msg, msg)

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                self._error(f"coordinator tick failed: {exc!r}")

    def _tick(self) -> None:
        now = time.monotonic()
        if now - self.last_inbox > 3.0:
            self.last_inbox = now
            new = self.store.scan_inbox()
            for e in new:
                self._on_new_entry(e)
            if new:
                self._bump("parts_rev")
                self.broadcast("project.changed", {"reason": f"{len(new)} file(s) picked up from the inbox"})
        if self.choice_pending is not None and now - self.choice_pending[1] >= SELECTOR_SETTLE_S:
            self._apply_choice(self.choice_pending[0], restart=True)
        settle = self.__dict__.get("_settle_at")
        if settle is not None and now >= settle:
            self._settle_at = None                     # the sliders have stopped: design / save the best layout now
            if self.run_status == "PAUSED":
                self._maybe_auto_design()
        if (self.ladders or self.studies) and now - self.last_ladder_poll > 1.0:
            self.last_ladder_poll = now
            self._poll_ladders()
            self._poll_studies()
        if now - self.last_memory > MEMORY_CHECK_S:
            self.last_memory = now
            self._enforce_memory()
        # V2: no automatic stop (it used to stop after 15 + 6 × speed/quality s without improvement, or after 6 h):
        # the search runs until Pause; the progress messages carry the running time and a recommended minimum
        if self.run_status == "SEARCHING":
            self._dispatch()
            self._dispatch_validation()
            if now - self.last_inject > 10.0:
                self.last_inject = now
                self._migrate()
            if now - self.last_norm_check > 5.0:
                self.last_norm_check = now
                self._maybe_new_epoch()
            if now - self.last_progress > PROGRESS_EVERY_S:
                self.last_progress = now
                self.broadcast("progress", self._progress())
        elif self.val_queue or self.val_pending:
            self._dispatch_validation()
        elif self.__dict__.get("_auto_design_due") and self.run_status == "PAUSED" and self._search_settled():
            self._auto_design_due = False              # the last search jobs and validations are done: the best is
            self._maybe_auto_design()                  # settled

    # =========================================================================================== records
    def _set_record(self, rec) -> None:
        self.records[rec.id] = rec
        self.geoms[rec.id] = part_geom_from_record(rec) if rec.status != "NEEDS_UNITS" else None
        self.build_errors.pop(rec.id, None)

    def _start_build(self, e: PartEntry, units: str) -> asyncio.Future:
        key = (e.id, units)
        if key in self.builds and not self.builds[key].done():
            return self.builds[key]
        cache = self.store.cache_path(e, units)
        if cache.exists():
            fut = self.loop.create_future()
            fut.set_result(str(cache))
        else:
            cf = self.build_pool.submit(build_record_file, str(self.store.stl_path(e)), str(cache), e.name, e.id, units,
                                        True, e.file)
            fut = asyncio.wrap_future(cf, loop=self.loop)
        self.builds[key] = fut
        fut.add_done_callback(lambda f, pid=e.id, u=units: self._on_build_done(pid, u, f))
        return fut

    def _on_build_done(self, pid: str, units: str, fut) -> None:
        e = self.store.entries.get(pid)
        if e is None or e.units != units:
            return
        if fut.cancelled():
            return
        if fut.exception() is not None:
            self.build_errors[pid] = f"analysis failed: {fut.exception()!r}"
            self._bump("parts_rev")
            self.broadcast("project.changed", {"reason": f"{e.name}: analysis failed"})
            return
        rec = self.store.load_record(e)
        if rec is None:
            self.build_errors[pid] = "analysis produced no record"
            return
        self._set_record(rec)
        self._refresh_inputs(f"part {e.name} analysed")
        self._maybe_auto_ladder(e)

    def _on_new_entry(self, e: PartEntry) -> None:
        try:
            self.quick[e.id] = quick_inspect(self.store.stl_path(e).read_bytes())
        except ValueError as exc:
            self.build_errors[e.id] = str(exc)
        self._start_build(e, e.units)          # speculative build with the suggested units

    def part_list(self) -> list[dict]:
        out = []
        for pid, e in self.store.entries.items():
            rec = self.records.get(pid)
            if rec is not None and rec.units != e.units:
                rec = None
            building = (pid, e.units) in self.builds and not self.builds[(pid, e.units)].done()
            d = part_json(e, rec, self.quick.get(pid) or self._quick(e), building=building)
            if pid in self.build_errors and rec is None:
                d["status"], d["status_detail"] = "WITHHELD", self.build_errors[pid]
            out.append(d)
        return jsonable(out)

    def _quick(self, e: PartEntry) -> dict:
        if e.id not in self.quick:
            try:
                self.quick[e.id] = quick_inspect(self.store.stl_path(e).read_bytes())
            except (ValueError, OSError):
                self.quick[e.id] = {}
        return self.quick[e.id]

    def _active_records(self) -> dict:
        out = {}
        for pid, e in self.store.entries.items():
            rec = self.records.get(pid)
            if rec is not None and rec.units == e.units and e.units_confirmed and packable(rec):
                out[pid] = rec
        return out

    # =========================================================================================== inputs
    def _bump(self, key: str) -> None:
        self.store.revs[key] = self.store.revs.get(key, 0) + 1
        self.store.save()

    # ------------------------------------------------------------------------------ part size (V2)
    def part_scale(self) -> float:
        """The part-size slider: Stage 2 only, 0.5 … 1.0 (full size)."""
        from ..parts.scale import PART_SCALE_MAX, PART_SCALE_MIN
        s = self.store.settings
        if int(s.get("stage", 1)) != 2:
            return 1.0
        return float(np.clip(float(s.get("part_scale_pct", 100)) / 100.0, PART_SCALE_MIN, PART_SCALE_MAX))

    def _ctx_scale(self) -> float:
        return self.ctx.part_scale if self.ctx is not None else 1.0

    def _scaled_entry(self, pid: str, scale: float):
        rec = self.records.get(pid)
        if rec is None:
            return None
        key = (pid, id(rec), round(float(scale), 6), rec.mass_override_kg, rec.density_kg_m3, rec.mass_source)
        hit = self._scaled.get(key)
        if hit is None:
            from ..parts.scale import scale_part
            hit = self._scaled[key] = [scale_part(rec, float(scale)), None]
            if len(self._scaled) > 400:                       # stale keys (old records, old masses)
                for k in list(self._scaled)[:200]:
                    del self._scaled[k]
        return hit

    def rec_at(self, pid: str, scale: float = 1.0):
        """The part's record at a part-size factor (the record itself at 1)."""
        if scale == 1.0:
            return self.records.get(pid)
        hit = self._scaled_entry(pid, scale)
        return hit[0] if hit else None

    def geom_at(self, pid: str, scale: float = 1.0):
        if scale == 1.0:
            return self.geoms.get(pid)
        hit = self._scaled_entry(pid, scale)
        if hit is None:
            return None
        if hit[1] is None:
            hit[1] = part_geom_from_record(hit[0])
        return hit[1]

    def layout_records(self, e) -> dict:
        """Records of a layout's parts at the size it was found at (reports, proofs, exports)."""
        return {pid: r for pid, _, _ in e.poses if (r := self.rec_at(pid, e.part_scale)) is not None}

    def layout_geoms(self, e) -> dict:
        return {pid: g for pid, _, _ in e.poses if (g := self.geom_at(pid, e.part_scale)) is not None}

    def _phys(self, scale: float = 1.0) -> dict:
        out = {}
        for pid in self._active_records():
            rec = self.rec_at(pid, scale)
            if rec.com_can_mm is None or rec.mass_kg is None:
                out[pid] = None
            else:
                out[pid] = PartPhys(float(rec.mass_kg), np.asarray(rec.com_can_mm, float), rec.inertia_com_kgm2())
        return out

    def _phys_wire(self) -> dict:
        return {pid: None if p is None else (p.mass_kg, p.com_can_mm.tolist(), p.inertia_com_kgm2.tolist())
                for pid, p in self._phys(self._ctx_scale()).items()}

    def _target(self) -> list[float]:
        return [float(x) for x in self.store.settings.get("target_com_mm", [0, 0, 0])]

    def _confirmed_builds_pending(self) -> int:
        n = 0
        for (pid, units), f in self.builds.items():
            e = self.store.entries.get(pid)
            if not f.done() and e is not None and e.units_confirmed and e.units == units:
                n += 1
        return n

    def _refresh_inputs(self, reason: str, bump_parts: bool = True) -> None:
        """Rebuild the search context if parts or constraints changed; re-stamp, re-score, re-select."""
        formfactor.set_form_factor(self.store.settings.get("form_factor", formfactor.DEFAULT))
        if bump_parts:
            self._bump("parts_rev")
        pending = self._confirmed_builds_pending()
        if pending:
            # wait for the last analysis so the workers restart once, not once per part
            if self.ctx is None:
                self._set_status("IDLE", f"analysing {pending} part(s)…")
            self.broadcast("project.changed", {"reason": reason})
            return
        recs = self._active_records()
        stage = int(self.store.settings.get("stage", 1))
        old = self.ctx
        if not recs:
            self.ctx = None
            self.ev = None
            self.best_id = None
            self._set_status("IDLE", "no packable parts")
            self.broadcast("project.changed", {"reason": reason})
            return
        ctx = build_context(recs, stage, {pid: self.reps[pid] for pid in recs if pid in self.reps},
                            stage2_mode=self._stage2_mode(), part_scale=self.part_scale(),
                            am_allowed=self._am_allowed(), form_factor=formfactor.current(),
                            am_level=self._am_level())
        self._sig_scale[ctx.parts_sig] = ctx.part_scale
        if old is None or ctx.ctx_id != old.ctx_id:
            if old is not None and (ctx.constraint_sig != old.constraint_sig or ctx.stage != old.stage) \
                    and ctx.parts_sig == old.parts_sig:
                self._bump("constraint_rev")
            self.ctx = ctx
            self.ctx_counter += 1
            self.ctx_path = write_context(ctx, self.store.cache / "contexts")
            self.norms.setdefault(ctx.ctx_id, Normaliser())
            self.raw_pool[ctx.ctx_id] = self.raw_pool.pop(ctx.ctx_id, [])
            for k in list(self.raw_pool)[:-TABLE_CACHE]:     # candidate pools of inputs left long ago (≤ 2000 each)
                del self.raw_pool[k]
            self._qual = {k: v for k, v in self._qual.items() if k[1] == ctx.ctx_id}
            self._clock_context(ctx.ctx_id)
            self.val_queue = []
            warm = []
            best = self.archive.get(self.best_id) if self.best_id else None
            if best is not None:
                warm.append(best.poses)
            self._apply_choice(self._compute_choice(), restart=False)
            for w in self.workers:
                self._send_context(w, warm)
            self._start_cpsat()
            if self.run_status == "IDLE" and (self.auto_start or self.search_requested):
                self._set_status("SEARCHING", f"inputs changed: {reason}")
        self.ev = Evaluator(None, ctx.ids, self._phys(ctx.part_scale), ctx.orient_bounds, ctx.z0, target=self._target(),
                            com_box=ctx.com_box, optional=self._optional_ids())
        self._restamp_and_rescore()
        self.broadcast("project.changed", {"reason": reason})
        self._publish_best("archive", force=True)
        if self.best_id is None and self.least_id is not None:
            self.broadcast("layout.infeasible", {"layout": self.layout_json(self.archive[self.least_id]),
                                                 "verdict": "NO FEASIBLE LAYOUT FOUND (not proven infeasible)"})

    def _send_context(self, w: WorkerHandle, warm=()) -> None:
        if self.ctx is None or self.ctx_path is None:
            return
        tag = (self.ctx.ctx_id, self.ctx_counter)
        if w.ctx_sent == tag:
            return
        w.ctx_sent = tag
        w.ctx_id = None
        w.busy = False
        islands = [x for x in self.workers if x.role == "island"]
        plans = island_plans(self.choice, len(islands)) if self.choice is not None else []
        w.plan = plans[islands.index(w)] if w.role == "island" and plans else {}
        w.cmd_q.put(("context", self.ctx.ctx_id, str(self.ctx_path), self.store.revs["mass_rev"], self._phys_wire(),
                     self._target(), list(warm), POP_SIZE, self.ctx_counter, w.plan))

    # =========================================================================================== selector
    def _part_stats(self):
        recs = self._active_records()
        sig = self.ctx.parts_sig if self.ctx is not None else None
        if self._stats is None or self._stats_sig != sig:
            self._stats = part_stats(list(recs.values()))
            self._stats_sig = sig
        return self._stats

    def _mode(self) -> str:
        s = self.store.settings
        return "continuous_cable" if int(s["stage"]) == 2 and float(s["sliders"].get("cable", 0)) >= 70 else "default"

    def _stage2_mode(self) -> str:
        from ..constraints.stage2_model import mode_for
        return mode_for(float(self.store.settings["sliders"].get("cable", 0)))

    def _am_allowed(self) -> bool:
        """V2 bracket budget: 0 = simple brackets only; above 0 a metal-AM bracket may stand in where needed."""
        return float(self.store.settings["sliders"].get("bracket_budget", 50)) > 0

    def _am_level(self) -> int:
        """V2 bracket budget step (mfg.rules.am_level): how strongly metal AM is preferred over simple brackets."""
        from ..mfg.rules import am_level
        return am_level(float(self.store.settings["sliders"].get("bracket_budget", 50)))

    def _compute_choice(self) -> AlgorithmChoice:
        s = self.store.settings
        return select_algorithm(int(s["stage"]), s["sliders"], self._part_stats(), self._mode(), self.evidence or None)

    def _apply_choice(self, choice: AlgorithmChoice, restart: bool) -> None:
        changed = self.choice is None or choice.id != self.choice.id
        self.choice = choice
        self.choice_pending = None
        if changed:
            self.selector_log.append({"at": now_iso(), "algorithm": choice.id, "reasons": choice.reasons})
            del self.selector_log[:-200]
        self.broadcast("selector.changed", self.selector())
        if changed and restart and self.ctx is not None:
            self.ctx_counter += 1
            best = self.archive.get(self.best_id) if self.best_id else None
            warm = [best.poses] if best is not None else []
            for w in self.workers:
                if w.role == "island":
                    self._send_context(w, warm)

    def _algo_for(self, w: WorkerHandle) -> dict:
        c = self.choice
        p = w.plan or {}
        detail = f"{SEARCH_LABELS.get(p.get('search'), p.get('search'))} on the {DECODER_LABELS.get(p.get('decoder'), '?')}"
        return {"id": c.id if c else "hybrid_box", "label": c.label if c else ALGORITHMS["hybrid_box"],
                "reason": c.reasons[0] if c and c.reasons else "", "search": p.get("search"), "decoder": p.get("decoder"),
                "island": w.id, "detail": detail}

    def _current(self, e: LayoutEntry) -> bool:
        """A layout is current when it was validated under the same parts and validation rules and satisfies the
        current allowed orientations and locks (so locking a part where it already is keeps the layout)."""
        if self.ctx is None:
            return False
        key = (e.id, self.ctx.ctx_id)
        q = self._qual.get(key)
        if q is None:
            q = self._qual[key] = self._qualifies(e, self.ctx)
        return q

    @staticmethod
    def _qualifies(e: LayoutEntry, ctx: SearchContext) -> bool:
        if e.parts_sig != ctx.parts_sig or e.stage != ctx.stage or e.spec_sig != ctx.spec_sig:
            return False
        um = lambda t: tuple(int(round(v * 1000)) for v in t)  # noqa: E731
        pose = {pid: (int(o), um(t)) for pid, o, t in e.poses}
        if set(pose) != set(ctx.ids):
            return False
        allowed = {p.id: set(p.allowed) for p in ctx.proxies}
        if any(o not in allowed[pid] for pid, (o, _) in pose.items()):
            return False
        return all(pose[pid] == (int(o), um(t)) for pid, o, t in ctx.fixed)

    def _restamp_and_rescore(self) -> None:
        """Re-stamp and re-score the layouts of the current inputs and choose the best. Their physics is recomputed
        when the inputs, the masses or the COM target changed (_ensure_table: the table key)."""
        self._ensure_table()
        for e in self.archive.values():
            if not self._current(e) or e.status not in ("VALIDATED", "FINAL", "INFEASIBLE"):
                continue
            e.revs = {k: self.store.revs[k] for k in REV_KEYS}
            self._score_entry(e)
        self._select_best()

    # ------------------------------------------------------------------------------ bounded archive (V2)
    def _hydrate(self, e: LayoutEntry) -> None:
        """A layout read back from archive.jsonl, brought up to date for the current inputs like the layouts in
        memory (physics with the current masses, revisions, score); a layout of other inputs stays as it was saved."""
        if self.__dict__.get("ctx") is None or e.status not in ("VALIDATED", "FINAL", "INFEASIBLE") \
                or not self._current(e):
            return
        self._compute_physics(e)
        e.revs = {k: self.store.revs[k] for k in REV_KEYS}
        self._score_entry(e)
        self.archive.note_status(e.id, e.status)    # the COM-box verdict can change with the masses

    def _table_key(self) -> tuple:
        """What the objective rows depend on besides the layouts: the inputs, the masses and the COM target."""
        return (self.ctx.ctx_id, self.store.revs.get("mass_rev", 0), tuple(float(x) for x in self._target()))

    def _ensure_table(self) -> ObjectiveTable | None:
        """The objective table of the current inputs (archive.py). It is kept up to date as layouts arrive; on a
        change of inputs, masses or COM target it is taken from the cache of recently searched inputs (if none of
        their layouts changed meanwhile) or rebuilt, and the physics of every layout of the current inputs is
        recomputed — in memory or read back one at a time."""
        if self.ctx is None:
            self._table = None
            return None
        key = self._table_key()
        t = self._table
        if t is not None and t.key == key:
            return t
        if t is not None:
            self._tables[t.key] = t
            while len(self._tables) > TABLE_CACHE:
                self._tables.popitem(last=False)
        fam = (self.ctx.stage, self.ctx.parts_sig, self.ctx.spec_sig)
        c = self._tables.pop(key, None)
        if c is not None and c.fam_ver == self._fam_ver.get(fam, 0):
            self._table = c                         # its rows are right; layouts in memory may have been recomputed
            for e in self.archive.values():         # for other masses or another COM target meanwhile
                if e.id in c and e.status in ("VALIDATED", "FINAL", "INFEASIBLE"):
                    self._compute_physics(e)
        else:
            self._table = self._build_table(key, fam)
        self._dfront = None
        return self._table

    def _build_table(self, key: tuple, fam: tuple) -> ObjectiveTable:
        """Rows for every layout of the current inputs: those in memory, then the others read back from archive.jsonl
        one at a time (brought up to date for the current inputs and dropped again: memory stays bounded)."""
        t = ObjectiveTable(key)
        t.fam_ver = self._fam_ver.get(fam, 0)
        ids = self.archive.ids_of(*fam)
        phys: dict = {}                             # part mass properties per part-size factor, once
        for lid in ids:
            if self.archive.is_hot(lid):
                self._table_row(t, self.archive[lid], phys)
        for _, e in self.archive.read_many(ids):
            self._table_row(t, e, phys)
        return t

    def _table_row(self, t: ObjectiveTable, e: LayoutEntry, phys: dict) -> None:
        if not self._current(e):
            return
        if e.status in ("VALIDATED", "FINAL", "INFEASIBLE"):
            if e.part_scale not in phys:
                phys[e.part_scale] = self._phys(e.part_scale)
            self._compute_physics(e, phys[e.part_scale])
            e.revs = {k: self.store.revs[k] for k in REV_KEYS}
            self._score_entry(e)
            self.archive.note_status(e.id, e.status)
        t.put(e.id, e.status, e.cv, e.raw)

    def _table_put(self, e: LayoutEntry) -> None:
        """A new or changed layout of the current inputs: its row in the table (and on the Pareto plot)."""
        t = self._table
        if t is None or self.ctx is None or t.key != self._table_key() or not self._current(e):
            return
        replaced = t.put(e.id, e.status, e.cv, e.raw)
        t.fam_ver = self._fam_ver.get((e.stage, e.parts_sig, e.spec_sig), 0)
        if replaced:
            self._dfront = None                     # a changed point can uncover others: the plot is recomputed
        elif e.status in OK_STATUSES:
            self._dfront_add(e.id, e.raw)

    def _g_rows(self, keys: tuple, m: np.ndarray) -> np.ndarray:
        """_score_raw for a block of table rows (columns 1… = keys), vectorised: the same arithmetic, equal up to the
        rounding of the final max/sum (the choices re-score their shortlist with _score_raw itself)."""
        norm = self._norm()
        if not norm.utopia:
            return m[:, 1 + keys.index("L")].copy() if "L" in keys else np.full(len(m), math.inf)
        nrm = {k: (m[:, 1 + j] - norm.utopia[k]) / (norm.nadir[k] - norm.utopia[k])
               for j, k in enumerate(keys) if k in norm.utopia}
        alpha = alpha_from(self.store.settings["sliders"])
        terms = []
        for k, w in self._weights().items():
            if k == "I":
                if "T" in nrm and "P" in nrm:
                    terms.append(w * (alpha * nrm["T"] + (1 - alpha) * nrm["P"]))
            elif k in nrm:
                terms.append(w * nrm[k])
        if not terms:
            return np.full(len(m), math.inf)
        a = np.vstack(terms)
        return a.max(axis=0) + RHO * a.sum(axis=0)

    def _pick(self, t: ObjectiveTable | None, cls: str) -> str | None:
        """The best layout of a class over every row of the table, in the order the archive scan used: (cv, g, L, id)
        for "ok" (VALIDATED / FINAL), (cv, g, id) for "inf" (INFEASIBLE). g is computed for all rows at once, then the
        near-ties are re-scored exactly."""
        if t is None:
            return None
        blocks = [(keys, ids, m, self._g_rows(keys, m)) for keys, ids, m in t.blocks(cls)]
        if not blocks:
            return None
        cv_min = min(float(m[:, 0].min()) for _, _, m, _ in blocks)
        g_min = min(float(g[m[:, 0] == cv_min].min()) for _, _, m, g in blocks if np.any(m[:, 0] == cv_min))
        tol = 1e-9 * max(1.0, abs(g_min)) if math.isfinite(g_min) else 0.0
        best = None
        for keys, ids, m, g in blocks:
            for i in np.flatnonzero((m[:, 0] == cv_min) & ((g <= g_min + tol) | (g == g_min))):
                raw = dict(zip(keys, m[i, 1:].tolist()))
                gx = self._score_raw(raw)[0]
                key = (cv_min, gx, raw.get("L", math.inf), ids[i]) if cls == "ok" else (cv_min, gx, ids[i])
                if best is None or key < best:
                    best = key
        return best[-1] if best is not None else None

    def _pick_loaded(self, cls: str) -> str | None:
        """_pick, skipping a layout whose archive line can no longer be read (it is dropped from the table)."""
        t = self._ensure_table()
        while True:
            lid = self._pick(t, cls)
            if lid is None or self.archive.get(lid) is not None:
                return lid
            t.discard(lid)

    def _enforce_memory(self) -> None:
        """Bounded memory for a search that never stops: once more than TOP_K + NEWEST_KEEP + HOT_SLACK layouts are in
        memory, keep only the pinned ones (best, least-violating, FINAL, the layout of a bracket design run or STL save
        under way, the last ones read on request), the TOP_K best-scoring layouts of the current inputs and the
        NEWEST_KEEP newest. The others stay in archive.jsonl, read back when asked for (archive.py)."""
        a = self.archive
        if not isinstance(a, LayoutArchive) or a.n_hot <= TOP_K + NEWEST_KEEP + HOT_SLACK:
            return
        keep = {self.best_id, self.least_id, self.__dict__.get("_stl_pending"), self._design_lid}
        keep |= {lid for lid, e in a.items() if e.status == "FINAL"}
        keep |= set(a.recent_ids()) | set(a.newest_ids(NEWEST_KEEP))
        cur = [e for e in a.values() if e.status in ("VALIDATED", "FINAL", "INFEASIBLE") and self._current(e)]
        cur.sort(key=lambda e: (e.cv, e.g, e.raw.get("L", math.inf), e.id))
        keep |= {e.id for e in cur[:TOP_K]}
        for lid in a.hot_ids():
            if lid not in keep:
                a.evict(lid)

    # ------------------------------------------------------------------------------ Pareto plot
    def _dfront_key(self) -> tuple:
        return (self._table.uid, self._table.changes, self._norm().epoch, alpha_from(self.store.settings["sliders"]))

    def _dpoint(self, raw: dict) -> tuple[float, float, float] | None:
        """(L̂, D̂, Î) of a layout under the current normaliser (what _score_raw reports as its normalised values)."""
        norm = self._norm()
        if not all(k in raw and k in norm.utopia for k in ("L", "D", "T", "P")):
            return None
        n = norm.norm({k: raw[k] for k in ("L", "D", "T", "P")})
        if len(n) < 4:
            return None
        alpha = alpha_from(self.store.settings["sliders"])
        return n["L"], n["D"], alpha * n["T"] + (1 - alpha) * n["P"]

    def _dfront_add(self, lid: str, raw: dict) -> None:
        d = self._dfront
        if d is None or self._table is None or d["key"] != self._dfront_key():
            return
        p = self._dpoint(raw)
        if p is None:
            return
        added, removed = d["front"].insert(lid, p)
        for k in removed:
            d["raw"].pop(k, None)
        if added:
            d["raw"][lid] = {k: raw[k] for k in raw if k in ("L", "D", "T", "P", "G", "H", "C", "O")}

    def _display_front(self) -> dict | None:
        """The non-dominated layouts of the current inputs in (L̂, D̂, Î): kept up to date as layouts arrive and
        recomputed from the objective table (O(N · front)) only when the normaliser, the mass-symmetry slider or a
        layout's values change."""
        t = self._ensure_table()
        if t is None:
            return None
        key = self._dfront_key()
        if self._dfront is not None and self._dfront["key"] == key:
            return self._dfront
        d = self._dfront = {"key": key, "front": ParetoFront(3), "raw": {}}
        pts = []
        for keys, ids, m in t.blocks("ok"):
            for i, lid in enumerate(ids):
                raw = dict(zip(keys, m[i, 1:].tolist()))
                p = self._dpoint(raw)
                if p is not None:
                    pts.append((p, lid, raw))
        pts.sort(key=lambda x: x[0])                # in L̂ order a later point never removes an earlier one
        for p, lid, raw in pts:
            added, removed = d["front"].insert(lid, p)
            for k in removed:
                d["raw"].pop(k, None)
            if added:
                d["raw"][lid] = raw
        return d

    # =========================================================================================== scoring
    def _weights(self) -> dict:
        s = self.store.settings
        return slider_weights(s["sliders"], int(s["stage"]), "default", optional=bool(self._optional_ids()))

    def _optional_ids(self) -> list[str]:
        """V2 optional parts (tag "optional"): the search may leave them out; objective O is the share left out."""
        if self.ctx is None:
            return []
        return [pid for pid, r in self.ctx.records.items() if "optional" in (r.tags or [])]

    def _norm(self) -> Normaliser:
        if self.ctx is None:
            return Normaliser()
        return self.norms.setdefault(self.ctx.ctx_id, Normaliser())

    def _score_raw(self, raw: dict) -> tuple[float, dict]:
        norm = self._norm()
        alpha = alpha_from(self.store.settings["sliders"])
        if not norm.utopia:
            return float(raw.get("L", math.inf)), {}
        n = norm.norm(raw)
        g = scalarise(n, self._weights(), alpha)
        out = {"L": n.get("L"), "D": n.get("D"),
               "I": (alpha * n["T"] + (1 - alpha) * n["P"]) if "T" in n and "P" in n else None,
               "G": n.get("G"), "H": n.get("H"), "C": n.get("C"), "O": n.get("O")}
        return g, out

    def _score_entry(self, e: LayoutEntry) -> None:
        e.g, e.normalised = self._score_raw(e.raw)
        e.norm_epoch = self._norm().epoch

    def _frame_mass(self) -> float:
        """Mass of the ASSUMED frame of the current CubeSat size (s2.frame_mass_props, once per size)."""
        cache = self.__dict__.setdefault("_frame_mass_cache", {})
        ff = formfactor.current()
        if ff not in cache:
            cache[ff] = s2.frame_mass_props()[0]
        return cache[ff]

    def _compute_physics(self, e: LayoutEntry, phys: dict | None = None) -> None:
        """Mass properties, objectives, cv and (Stage 2) status of a layout for the current masses and COM target.
        phys: self._phys(e.part_scale), when the caller has it already (the objective table, layout after layout)."""
        phys = self._phys(e.part_scale) if phys is None else phys
        items, excluded = [], []
        for pid, o, t in e.poses:
            p = phys.get(pid)
            if p is None:
                excluded.append(pid)
                continue
            r = ROTATIONS_F[o]
            items.append((p.mass_kg, r @ p.com_can_mm + t, r @ p.inertia_com_kgm2 @ r.T))
        hardware = []
        if e.meta.get("hardware"):                 # Manufacturable Design: every bracket, spacer and standoff
            hardware = [(m, np.asarray(c, float), np.asarray(i, float)) for m, c, i in e.meta["hardware"]]
            items += hardware
        elif e.meta.get("standoffs") or e.meta.get("brackets") or e.meta.get("stack_hardware"):
            from ..constraints.stage2_model import Stage2Model
            hardware = Stage2Model.standoff_mass(e.meta.get("standoffs") or [])
            designs = e.meta.get("bracket_designs") or {}
            for b in e.meta.get("brackets") or []:                          # V2 Stage 2 brackets
                d = designs.get(b["pid"]) if designs.get(b["pid"], {}).get("mass_kg") is not None else None
                src = d or b                                                # a designed solid replaces the estimate
                hardware.append((src["mass_kg"], np.asarray(src["com_mm"], float), np.asarray(src["inertia_kgm2"], float)))
            for h in e.meta.get("stack_hardware") or []:   # v2.5: PC/104 rods and spacer tubes, as in the search
                hardware.append((h["mass_kg"], np.asarray(h["com_mm"], float), np.asarray(h["inertia_kgm2"], float)))
            items += hardware
        m = dict(e.geo)
        if hardware:
            m["hardware_mass_kg"] = float(sum(h[0] for h in hardware))
        m["mass_excluded_parts"] = excluded
        raw = {"L": e.geo["length_used_mm"], "span": e.geo["span_mm"]}
        if "margin_objective" in e.geo and e.stage == 2:
            raw["G"] = e.geo["margin_objective"]
        if e.stage == 2:                            # cable path and hardware cost travel with the layout
            raw.update({k: float(e.meta[k]) for k in ("H", "C") if e.meta.get(k) is not None})
            if e.meta.get("C") is not None:
                m["hardware_cost_rel"] = e.meta.get("hardware_cost_rel", float(e.meta["C"]))
        if (e.meta or {}).get("O") is not None:      # V2 optional parts left out of this layout
            raw["O"] = float(e.meta["O"])
            m["optional_left_out"] = list(e.meta.get("dropped", []))
        if items:
            a = assembly([], [], np.zeros((0, 3)), items)
            im = inertia_metrics(a.inertia_kgm2)
            cb = com_box_check(a.com_mm, self._target())
            m.update({"mass_kg": a.mass_kg, "com_mm": a.com_mm.tolist(), "inertia_kgm2": a.inertia_kgm2.tolist(), **im, **cb})
            if e.stage == 2:
                m["frame_mass_kg"] = self._frame_mass()
                m["com_box_note"] = "CDS COM box checked on the parts only (frame mass excluded, decision U7)"
            raw.update({"D": cb["com_error_mm"], "T": im["trace_kgm2"], "P": im["products_norm_kgm2"],
                        "lambda_max": im["lambda_max_kgm2"], "com": a.com_mm.tolist()})
            if excluded:
                m["mass_note"] = f"incomplete — {len(excluded)} part(s) excluded (mass properties withheld)"
            e.cv = 0.0
            if e.stage == 2:
                if excluded:
                    m["com_box_ok"] = None
                    m["com_box_verdict"] = "NOT ASSESSABLE"
                excess = np.maximum(np.abs(a.com_mm) - formfactor.COM_BOX, 0)
                e.cv = float(excess.sum() / 10.0)
        if e.stage == 2:
            ev_ = list(e.validation.get("engineering_violations", []))
            e.cv += float(len(e.meta.get("unmounted", []))) + float(e.meta.get("overflow_mm", 0.0)) / 10.0
            if m.get("com_box_ok") is False:
                ev_.append("COM outside the CDS box (|x| ≤ 20, |y| ≤ 20, |z| ≤ 70 mm): "
                           f"({m['com_mm'][0]:.1f}, {m['com_mm'][1]:.1f}, {m['com_mm'][2]:.1f}) mm")
            if m.get("com_box_ok") is None and excluded:
                ev_.append("COM box NOT ASSESSABLE: mass properties withheld for " + ", ".join(excluded))
            m["violations"] = ev_
            m["cable_blocked_fraction"] = e.meta.get("H")
            # e.meta["mounts"] itself, set below: already JSON-safe, and running jsonable over it again took most of
            # this function's time
            m["mounting"] = None
            if e.status in ("VALIDATED", "INFEASIBLE"):
                if not e.validation.get("certified"):
                    e.status = "REJECTED"
                elif ev_ or e.cv > 0:
                    e.status = "INFEASIBLE"
                else:
                    e.status = "VALIDATED"
        m.setdefault("insertion_order", None)
        m.setdefault("interlocked", [])
        m.setdefault("cable_blocked_fraction", None)
        m.setdefault("hardware_cost_rel", e.meta.get("hardware_cost_rel"))
        e.metrics = jsonable(m)
        if e.stage == 2:
            e.metrics["mounting"] = e.meta.get("mounts")
        e.raw = raw

    def _select_best(self) -> None:
        """The best VALIDATED / FINAL layout of the current inputs by (cv, g, L, id), over every layout of them — in
        memory or not (the objective table); the chosen one is read back into memory if it was not."""
        lid = self._pick_loaded("ok")
        if lid is None:
            self.best_id = None
        elif lid != self.best_id:
            self.best_id = lid
            if self.run_status == "PAUSED":            # a late validation while paused: design it too
                self._maybe_auto_design()
        self._select_least(publish=False)

    def _select_least(self, publish: bool = True) -> None:
        """Stage 2 with no feasible layout: the least-violating certified candidate (shown, never as VALIDATED)."""
        prev = self.least_id
        self.least_id = None if self.best_id is not None else self._pick_loaded("inf")
        if publish and self.least_id is not None and self.least_id != prev:
            self.broadcast("layout.infeasible", {"layout": self.layout_json(self.archive[self.least_id]),
                                                 "verdict": "NO FEASIBLE LAYOUT FOUND (not proven infeasible)"})

    def _maybe_new_epoch(self, force: bool = False) -> None:
        if self.ctx is None:
            return
        norm = self._norm()
        # the archived layouts count through their smallest and largest values (all the normaliser takes from them)
        t = self._ensure_table()
        lo, hi, n = t.extremes("D") if t is not None else ({}, {}, 0)
        pool = [r for r in self.raw_pool.get(self.ctx.ctx_id, [])[-300:] if "D" in r]
        if n + len(pool) < 10:
            return
        raws = ([lo, hi] if n else []) + pool
        if not force and norm.utopia:
            # only when some value fell outside the current range by > 5 % of it
            out = False
            for k in ("L", "D", "T", "P"):
                if k not in norm.utopia:
                    continue
                lo_k, hi_k = norm.utopia[k], norm.nadir[k]
                span = hi_k - lo_k
                vals = [r[k] for r in raws if k in r]
                if vals and (min(vals) < lo_k - 0.05 * span or max(vals) > hi_k + 0.05 * span):
                    out = True
            if not out:
                return
        norm.update_from(raws)
        prev = self.best_id
        for e in self.archive.values():
            if self._current(e):
                self._score_entry(e)
        self._select_best()
        if self.best_id != prev:
            self._publish_best("archive")
        self.broadcast("pareto.update", self.pareto())

    # =========================================================================================== search
    def _set_status(self, status: str, detail: str = "") -> None:
        if status == self.run_status and detail == self.status_detail:
            return
        self._clock(status)
        self.run_status, self.status_detail = status, detail
        self.broadcast("status", {"run_status": status, "detail": detail})
        if self.clients:
            self.broadcast("progress", self._progress())    # the running time as it stands (it stops while paused)
        if status == "PAUSED":                              # Pause is the only stop: it starts the bracket design
            self._maybe_auto_design()

    def _clock(self, status: str) -> None:
        """The running time: time spent SEARCHING, per search context (pauses do not count)."""
        now = time.monotonic()
        if self._search_since is not None and status != "SEARCHING":
            self._searched[self._search_ctx] = self._searched.get(self._search_ctx, 0.0) + now - self._search_since
            self._search_since = None
        elif self._search_since is None and status == "SEARCHING":
            self._search_since = now
            self._search_ctx = self.ctx.ctx_id if self.ctx is not None else None

    def _clock_context(self, ctx_id: str | None) -> None:
        """New inputs: the time searched so far counts for the old ones; a running clock goes on for the new ones (and
        on a return to inputs searched before, adds to their time)."""
        if self._search_since is not None:
            now = time.monotonic()
            self._searched[self._search_ctx] = self._searched.get(self._search_ctx, 0.0) + now - self._search_since
            self._search_since = now
        self._search_ctx = ctx_id

    def _clock_restart(self) -> None:
        """Re-run / reset: the running time of the current inputs starts again from zero."""
        self._searched.pop(self._search_ctx, None)
        if self._search_since is not None:
            self._search_since = time.monotonic()

    def searching_s(self) -> float:
        """Seconds spent SEARCHING for the current inputs (the "running M min" of the status bar)."""
        ctx_id = self.ctx.ctx_id if self.ctx is not None else None
        s = self._searched.get(ctx_id, 0.0)
        if self._search_since is not None and self._search_ctx == ctx_id:
            s += time.monotonic() - self._search_since
        return s

    def _dispatch(self) -> None:
        if self.ctx is None:
            return
        weights = self._weights()
        alpha = alpha_from(self.store.settings["sliders"])
        norm = self._norm()
        nw = {"epoch": norm.epoch, "utopia": norm.utopia, "nadir": norm.nadir}
        for k, w in enumerate(x for x in self.workers if x.role == "island"):
            if not w.ready or w.busy or w.ctx_id != self.ctx.ctx_id:
                continue
            self.job_counter += 1
            w.busy, w.job = True, self.job_counter
            w.cmd_q.put(("run", w.job, self.ctx.ctx_id, SLICE_S, perturbed_weights(weights, k), alpha, nw, 3))

    def _dispatch_validation(self) -> None:
        idle = [w for w in self.workers if w.role == "validator" and w.ready and not w.busy]
        while idle and self.val_queue:
            self.val_queue.sort(key=lambda x: x["key"])
            item = self.val_queue.pop(0)
            ctx_id = item["ctx_id"]
            w = next((w for w in idle if w.ctx_id == ctx_id), None)
            if w is None:
                if self.ctx is not None and ctx_id != self.ctx.ctx_id:
                    self.pending_hashes.discard(item["h"])
                    continue                  # older inputs: nobody can validate it any more
                self.val_queue.insert(0, item)
                break
            idle.remove(w)
            self.job_counter += 1
            w.busy, w.job = True, self.job_counter
            self.val_pending[w.job] = item
            w.cmd_q.put(("validate", w.job, ctx_id, item["poses"], False, bool(item["compact"]), item["meta"]))

    def _migrate(self) -> None:
        if self.ctx is None or self.best_id is None:
            return
        best = self.archive[self.best_id]
        if best.keys is None or not self._current(best):  # only a chromosome of this context (the islands also skip
            return                                       # one of another length: worker.fitting_keys)
        for w in self.workers:
            if w.role == "island" and w.ctx_id == self.ctx.ctx_id:
                w.cmd_q.put(("inject", self.ctx.ctx_id, [best.keys]))

    def _on_worker_msg(self, msg) -> None:
        kind = msg[0]
        if kind == "ready":
            w = self.workers[msg[1]]
            w.ready = True
            self._send_context(w)
        elif kind == "context_ok":
            self.workers[msg[1]].ctx_id = msg[2]
            self.workers[msg[1]].info = msg[3] if len(msg) > 3 else {}
        elif kind == "island":
            self._on_island(*msg[1:])
        elif kind == "validated":
            self._on_validated(*msg[1:])
        elif kind == "error":
            w = self.workers[msg[1]]
            w.busy = False
            self._error(f"worker {msg[1]} ({w.role}): {msg[2]}", msg[3])

    def _on_island(self, wid, job, ctx_id, mass_rev, evals, gens, cands, note) -> None:
        w = self.workers[wid]
        w.busy = False
        w.evaluations += evals
        w.generations += gens
        self.evaluations += evals
        if self.ctx is None or ctx_id != self.ctx.ctx_id:
            return
        best_cand = None
        best_g_now = self.archive[self.best_id].g if self.best_id else math.inf
        least = self.archive.get(self.least_id) if self.least_id else None
        pool = self.raw_pool.setdefault(ctx_id, [])
        table = self._ensure_table()                 # every validated layout of these inputs, in memory or not
        has_cur = table is not None and table.count("ok") > 0
        sigs = (self.ctx.parts_sig, self.ctx.constraint_sig, self.ctx.stage, self.ctx.spec_sig)
        for c in cands:
            if c["unplaced"]:
                continue
            raw_extra = {k: c["raw"][k] for k in ("H", "C", "O") if k in c["raw"]}
            raw, cv = self.ev.raw_from_poses(c["poses"], c["unplaced"], c.get("penalty", 0.0),
                                             [(m, np.asarray(p), np.asarray(i)) for m, p, i in c.get("extra_mass", [])],
                                             raw_extra)
            g, nrm = self._score_raw(raw)
            h = layout_hash(self.ctx.stage, c["poses"])
            item = {"key": (cv, g), "g": g, "cv": cv, "h": h, "poses": c["poses"], "raw": raw,
                    "keys": np.asarray(c["keys"]).tolist(), "ctx_id": ctx_id, "sigs": sigs, "algo": self._algo_for(w),
                    "compact": False, "meta": c.get("meta"), "kind": "search"}
            if cv > 0:
                # Stage 2 without a feasible layout yet: certify the least-violating candidate (protocol §F.2)
                if self.ctx.stage == 2 and not has_cur and h not in self.by_hash and h not in self.pending_hashes and \
                        (least is None or (cv, g) < (least.cv, least.g)) and \
                        not any(x["kind"] == "least" for x in self.val_queue) and \
                        not any(x["kind"] == "least" for x in self.val_pending.values()):
                    item["kind"] = "least"
                    self.pending_hashes.add(h)
                    self.val_queue.append(item)
                continue
            pool.append(raw)
            if w.best_g is None or g < w.best_g:
                w.best_g = g
            if best_cand is None or g < best_cand[0]:
                best_cand = (g, h, c, raw, nrm)
            if h in self.by_hash or h in self.pending_hashes:
                continue
            keys3 = ("L", "D", "T")
            nondom = all(k in raw for k in keys3) and not (table is not None and table.dominated(raw, keys3))
            if g < best_g_now - 1e-12 or nondom:
                self.pending_hashes.add(h)
                # a would-be new best from the box decoder also gets certified drop compaction (Stage 1)
                item["compact"] = g < best_g_now - 1e-12 and w.plan.get("decoder") == "box" and self.ctx.stage == 1
                self.val_queue.append(item)
        if len(pool) > 2000:
            del pool[:1000]
        if len(self.val_queue) > 24:
            self.val_queue.sort(key=lambda x: x["key"])
            for item in self.val_queue[24:]:
                self.pending_hashes.discard(item["h"])
            del self.val_queue[24:]
        now = time.monotonic()
        if best_cand is not None and now - self.last_candidate > CANDIDATE_EVERY_S and \
                any(c.want_candidates for c in self.clients):
            self.last_candidate = now
            g, h, c, raw, nrm = best_cand
            self.candidate = self._candidate_json(h, c["poses"], raw, g, nrm)
            self.broadcast("layout.candidate", {"layout": self.candidate}, only=lambda cl: cl.want_candidates)
        self._continue_search()
        self._dispatch_validation()

    def _continue_search(self) -> None:
        """Give the island that just reported its next job — only while searching. (It used to dispatch whatever the
        status, so after a stop the islands kept searching: CPU busy, new layouts arriving, the best changing under a
        paused search.)"""
        if self.run_status == "SEARCHING":
            self._dispatch()

    def _on_validated(self, wid, job, ctx_id, summary, extra=None) -> None:
        w = self.workers[wid]
        w.busy = False
        item = self.val_pending.pop(job, None)
        if item is None:
            return
        h, poses, sigs, keys = item["h"], item["poses"], item["sigs"], item["keys"]
        self.pending_hashes.discard(h)
        if summary is None:                    # the validator had switched context: retry if still relevant
            if self.ctx is not None and item["ctx_id"] == self.ctx.ctx_id:
                self.pending_hashes.add(h)
                self.val_queue.append(item)
            return
        decoded_hash = h
        algo = dict(item["algo"])
        if extra and extra.get("poses"):
            poses = extra["poses"]
            h = layout_hash(sigs[2], poses)
            algo["detail"] += " + certified drop compaction"
            algo["compaction"] = {"moved_mm": {k: v for k, v in extra["moved_mm"].items() if v > 0},
                                  "seconds": extra["seconds"]}
        meta = item.get("meta") or {}
        scale = self._sig_scale.get(sigs[0], 1.0)
        geo = self._geo_metrics(poses, summary, sigs[2], scale)
        if sigs[2] == 2:
            order = summary.get("insertion_order")
            geo["insertion_order"] = [p for p, _ in order] if order else None
            geo["insertion_directions"] = [u for _, u in order] if order else None
        n = self.store.next_id("layout")
        e = LayoutEntry(id=f"L-{n:04d}", hash=h, stage=sigs[2], mode=_mode_name(meta), algorithm=algo,
                        status="VALIDATED" if summary["valid"] else "REJECTED", parts_sig=sigs[0], constraint_sig=sigs[1],
                        poses=[(pid, int(o), np.asarray(t, float)) for pid, o, t in poses], geo=geo,
                        validation={"certified": bool(summary["valid"]), "validator_version": summary["validator_version"],
                                    "tolerance_mm": 0.001, "pairs": summary["pairs"], "statics": summary["statics"],
                                    "levels": summary["levels"], "min_clearance_mm": summary["min_clearance_mm"],
                                    "seconds": summary["seconds"], "checked_at": now_iso(),
                                    "violations": summary["violations"],
                                    "engineering_violations": summary.get("engineering_violations", []),
                                    "relaxed_rules": bool(summary.get("relaxed"))},
                        keys=keys, spec_sig=sigs[3], meta=jsonable(meta), part_scale=scale)
        if not summary["valid"]:
            self._error(f"validator rejected decoder layout {e.id}: {summary['violations'][:3]}")
        self._admit(e, (h, decoded_hash))

    def _admit(self, e: LayoutEntry, hashes: tuple = ()) -> None:
        """A newly validated layout: scored, archived (memory and archive.jsonl, its objective row if it belongs to
        the current inputs), then the best or least-violating layout is chosen again."""
        self._compute_physics(e)
        e.revs = {k: self.store.revs[k] for k in REV_KEYS}
        self._score_entry(e)
        self.archive[e.id] = e
        for h in hashes or (e.hash,):
            self.by_hash[h] = e.id
        self._persist(e)
        if self._current(e) and e.status == "INFEASIBLE":
            self._select_least()
            return
        if not self._current(e) or e.status != "VALIDATED":
            return
        prev = self.best_id
        self._select_best()
        if self.best_id != prev:
            self._publish_best("search")
            self.best_g_hist.append((time.monotonic(), e.g))
            del self.best_g_hist[:-1000]
            if self.best_id == e.id and "slab" not in e.algorithm.get("detail", ""):
                self._slab_polish(e)
        if time.monotonic() - self.last_pareto > 2.0:
            self.last_pareto = time.monotonic()
            self.broadcast("pareto.update", self.pareto())

    def _orient_equiv(self, pid: str) -> list[int]:
        cache = self.__dict__.setdefault("_equiv_cache", {})
        rec = self.records[pid]
        key = (pid, rec.sha256, rec.units)
        if key not in cache:
            from ..parts.build import orient_equivalence
            cache[key] = orient_equivalence(rec.v)
        return cache[key]

    def _slab_polish(self, e: LayoutEntry, limit: int = 300, keep: int = 3) -> None:
        """Slab post-optimiser (A1): reorder / rotate / flip Z-slabs of a new best at constant used length and queue
        the variants that score better under the current weights for validation."""
        if self.ctx is None or self.ev is None or self.ctx.fixed or e.stage != 1:
            return
        from ..optimise.slabs import slab_candidates
        zint = []
        for pid, o, t in e.poses:
            b = self.ctx.orient_bounds[pid][o]
            zint.append((float(t[2] + b[2]), float(t[2] + b[5])))
        allowed = {p.id: set(p.allowed) for p in self.ctx.proxies}
        equiv = {pid: self._orient_equiv(pid) for pid, _, _ in e.poses}
        scored = []
        rng = np.random.default_rng(len(self.archive))
        for k, cand in enumerate(slab_candidates(e.poses, zint, rng=rng)):
            if k >= limit:
                break
            # a rotated symmetric part is the same solid as its representative orientation (same vertex set)
            cand = [(pid, int(equiv[pid][o]), t) for pid, o, t in cand]
            if any(o not in allowed[pid] for pid, o, _ in cand):
                continue                       # a rotated slab must keep every part in its allowed orientations
            cand = [(pid, int(o), np.round(np.asarray(t, float) * 1000.0) / 1000.0) for pid, o, t in cand]
            raw, cv = self.ev.raw_from_poses(cand, [])
            if cv > 0:
                continue
            g, _ = self._score_raw(raw)
            if g < e.g - 1e-9:
                scored.append((g, cand, raw))
        scored.sort(key=lambda x: x[0])
        algo = dict(e.algorithm)
        algo["detail"] = algo.get("detail", "") + " + slab post-optimiser"
        sigs = (e.parts_sig, e.constraint_sig, e.stage, e.spec_sig)
        for g, cand, raw in scored[:keep]:
            h = layout_hash(e.stage, cand)
            if h in self.by_hash or h in self.pending_hashes:
                continue
            self.pending_hashes.add(h)
            self.val_queue.append({"key": (0.0, g), "g": g, "cv": 0.0, "h": h, "poses": cand, "raw": raw,
                                   "keys": e.keys, "ctx_id": self.ctx.ctx_id, "sigs": sigs, "algo": algo,
                                   "compact": False, "meta": None, "kind": "slab"})

    def _geo_metrics(self, poses, summary, stage: int, scale: float = 1.0) -> dict:
        tops, bottoms, vol = [], [], 0.0
        for pid, o, t in poses:
            hw = to_world(self.geom_at(pid, scale).hull_pts, o, np.asarray(t, float))
            tops.append(hw[:, 2].max())
            bottoms.append(hw[:, 2].min())
            vol += self.rec_at(pid, scale).volume_mm3 or 0.0
        z0 = float(ENCLOSURE_LO[2])
        req = s2.C_PP if stage == 2 else 0.0
        mc = summary["min_clearance_mm"]
        slack = max(0.0, (mc if mc is not None and math.isfinite(mc) else 5.0) - req)
        return jsonable({
            "length_used_mm": float(max(tops) - z0), "span_mm": float(max(tops) - min(bottoms)),
            "free_length_mm": float(ENCLOSURE_HI[2] - max(tops)),
            "space_used": float(vol / float(np.prod(ENCLOSURE_HI - ENCLOSURE_LO))), "parts_placed": len(poses),
            "min_clearance_mm": mc, "required_clearance_mm": req, "margin_objective": float(1.0 - min(1.0, slack / 5.0)),
            "largest_empty_box_mm": [float(ENCLOSURE_HI[0] - ENCLOSURE_LO[0]), float(ENCLOSURE_HI[1] - ENCLOSURE_LO[1]),
                                     float(ENCLOSURE_HI[2] - max(tops))] if stage == 1 else None,
        })

    # =========================================================================================== publishing
    def _publish_best(self, source: str, force: bool = False) -> None:
        if self.best_id is None:
            return
        e = self.archive[self.best_id]
        self.broadcast("layout.validated", {"layout": self.layout_json(e), "source": source})

    def _progress(self) -> dict:
        """Progress message. elapsed_s is the running time: seconds spent SEARCHING for the current inputs (pauses
        do not count); recommended_min_s the provisional, search-based minimum for this CubeSat size (None where
        nothing was measured yet; bench/convergence_table.py)."""
        best = self.archive.get(self.best_id) if self.best_id else None
        ff = formfactor.current()
        rec = recommended_minimum(ff)
        t = self._table if self.ctx is not None else None
        return jsonable({
            "status": self.run_status, "evaluations": self.evaluations, "best_g": best.g if best else None,
            "best_length_mm": best.raw.get("L") if best else None,
            "elapsed_s": self.searching_s(),
            "recommended_min_s": rec["minimum_s"] if rec else None,
            "recommended_note": rec["note"] if rec else f"No recommended minimum has been measured for {ff} yet.",
            "validation_queue": len(self.val_queue), "validating": len(self.val_pending),
            "archive": len(t) if t is not None else 0,
            "islands": [{"id": w.id, "kind": "brkga", "evaluations": w.evaluations, "generations": w.generations,
                         "best_g": w.best_g, "ready": w.ready and self.ctx is not None and w.ctx_id == self.ctx.ctx_id}
                        for w in self.workers if w.role == "island"],
        })

    def _error(self, message: str, detail: str | None = None) -> None:
        self.errors.append(message + ("\n" + detail if detail else ""))
        del self.errors[:-50]
        self.broadcast("error", {"message": message})

    def pose_json(self, poses) -> list[dict]:
        return [{"part_id": pid, "orient": int(o), "t_um": [int(round(v * 1000)) for v in t]} for pid, o, t in poses]

    def layout_list(self, status: str | None = None, limit: int = 200, current: bool | None = None) -> list:
        """The newest archived layouts (GET /api/layouts), newest first by layout number; layouts not in memory are
        read back for this answer only."""
        ids = sorted((lid for lid in self.archive if not status or self.archive.status_of(lid) == status),
                     key=_layout_order, reverse=True)
        out = []
        for lid in ids:
            if len(out) >= limit:
                break
            e = self.archive.load(lid, keep=False)
            if e is not None and (not status or e.status == status) and (current is None or self._current(e) == current):
                out.append(e)
        return out

    def layout_json(self, e: LayoutEntry, full: bool = True) -> dict:
        d = {
            "id": e.id, "hash": e.hash, "stage": e.stage, "mode": e.mode, "status": e.status,
            **{k: e.revs.get(k, 0) for k in ("parts_rev", "constraint_rev", "mass_rev", "weights_rev")},
            "metrics": e.metrics,
            "scores": {"normalised": e.normalised, "g": _f(e.g), "norm_epoch": e.norm_epoch},
            "algorithm": e.algorithm, "validation": e.validation, "origin": e.origin, "created": e.created,
            "part_ids": [p[0] for p in e.poses], "current": self._current(e), "part_scale": e.part_scale,
        }
        if e.stage == 2:
            d["label"] = "ENGINEERING-CONSTRAINED — not flight-qualified"
            d["violations_engineering"] = e.metrics.get("violations", [])
            if e.status == "INFEASIBLE":
                d["verdict"] = "NO FEASIBLE LAYOUT FOUND (not proven infeasible)"
        if full:
            d["poses"] = self.pose_json(e.poses)
            d["extra_items"] = self._extra_items(e)
            if e.stage == 2:
                d["stage2"] = self._stage2_view(e)
        return jsonable(d)

    def _extra_items(self, e: LayoutEntry) -> list[dict]:
        from ..constraints.stage2_model import Stage2Model
        if e.meta.get("mfg_items") is not None:
            return [{k: v for k, v in it.items() if k != "file"} for it in e.meta["mfg_items"]]
        out = []
        st = e.meta.get("standoffs") or []
        masses = Stage2Model.standoff_mass(st)
        for k, ((pid, b), (m, _, _)) in enumerate(zip(st, masses)):
            out.append({"id": f"{e.id}-so{k}", "kind": "standoff", "process": "standoff", "for_part": pid,
                        "mesh_url": f"/api/items/{e.id}-so{k}/mesh", "mass_kg": m, "cost_rel": None,
                        "material": "aluminium (ASSUMED)", "label": "M3 standoff (ASSUMED 5 × 5 mm envelope)",
                        "box_mm": b})
        for k, b in enumerate(e.meta.get("brackets") or []):        # V2 Stage 2 brackets (designed solid if any)
            d = (e.meta.get("bracket_designs") or {}).get(b["pid"])
            d = d if d and d.get("mass_kg") is not None else None    # a failed design keeps the estimate
            # a designed solid gets its own URL: viewers cache meshes by URL and must not keep showing the box
            ver = f"?v=d{int(round(d['mass_kg'] * 1e7))}" if d else ""
            out.append({"id": f"{e.id}-br{k}", "kind": "bracket", "bracket_kind": b["kind"], "process": b["process"],
                        "for_part": b["pid"], "mesh_url": f"/api/items/{e.id}-br{k}/mesh{ver}",
                        "designed": bool(d),
                        "mass_kg": d["mass_kg"] if d else b["mass_kg"], "cost_rel": d["cost_rel"] if d else b["cost_rel"],
                        "material": b["material"], "label": d["label"] if d else b["label"],
                        "exact": True if d else b["exact"], "box_mm": b["reserve"], "target": b["target"]})
        boxes = dict(self._rod_boxes(e))
        board = (e.meta.get("stack_ids") or [None])[0]     # the rods move with the boards in the exploded view
        end = {"-z": "−Z", "+z": "+Z"}.get(e.meta.get("rod_end"), "")
        for k, h in enumerate(e.meta.get("stack_hardware") or []):   # v2.5: PC/104 rods with their spacer tubes
            nm = str(h["name"])                                       # "rod+-": the rod at +x, −y
            where = (f" at {'−' if nm[3] == '-' else '+'}x {'−' if nm[4] == '-' else '+'}y"
                     if len(nm) == 5 and nm.startswith("rod") else f" {nm}")
            out.append({"id": f"{e.id}-rod{k}", "kind": "rod", "process": "standoff", "for_part": board,
                        "mesh_url": f"/api/items/{e.id}-rod{k}/mesh", "mass_kg": h["mass_kg"], "cost_rel": None,
                        "material": "M3 steel rod, aluminium spacer tube (ASSUMED)",
                        "label": f"PC/104 rod{where} with spacer tube, to the {end} end plate",
                        "box_mm": [float(x) for x in boxes.get(h["name"], [])], "target": f"{end} end plate"})
        return out

    @staticmethod
    def _rod_boxes(e: LayoutEntry) -> list:
        """The PC/104 rods of a layout as (name, box), in the current frame (stage2_model.stack_rods)."""
        from ..constraints.stage2_model import stack_rods
        return stack_rods(e.meta or {}) if (e.meta or {}).get("rod_end") else []

    def _stage2_view(self, e: LayoutEntry) -> dict:
        """Rules this layout was decoded under, for display (rails, harness / corridor, rods, stack block)."""
        meta = e.meta or {}
        frame = []
        if self.ctx is not None and self.ctx.stage == 2:
            try:
                for s in self.ctx.stage2_model().statics(meta):
                    frame.append({"kind": s.kind, "id": s.name, "min": s.corners.min(0).tolist(),
                                  "max": s.corners.max(0).tolist()})
            except Exception:  # noqa: BLE001
                frame = []
        return {"mode": meta.get("mode"), "corridor": meta.get("corridor"), "stack_span_mm": meta.get("stack_span"),
                "overflow_mm": meta.get("overflow_mm"), "unmounted": meta.get("unmounted", []),
                "mounts": meta.get("mounts", {}), "cable_blocked_fraction": meta.get("H"), "frame": frame,
                "insertion_order": e.geo.get("insertion_order"), "com_shift_mm": meta.get("com_shift_mm"),
                "com_z_unshifted_mm": meta.get("com_z_unshifted_mm"), "rod_end": meta.get("rod_end"),
                "brackets": meta.get("brackets", []),
                "hardware_cost_rel": meta.get("C"), "bracket_designs": meta.get("bracket_designs", {}),
                "bracket_overrides": meta.get("bracket_overrides", {}),
                "assumed": ["2 mm walls", "8.5 mm corner rails", "clearances 2.2 / 1.2 mm (U4)",
                            ("PC/104 stack, 15.24 mm pitch, rods at (±35, ±35) mm × part size, anchored at the "
                             "nearest end plate (M3 rods in 5 mm spacer tubes)"), "3 mm mounting layer (U6)",
                            ("V2 brackets: one per part to a wall, end plate or corner rail ≤ 40 mm away; "
                             "each reserved box keeps 1.2 mm from other parts, brackets and keep-outs; relative "
                             "costs, cradle / metal-AM masses estimated until designed"),
                            "10 mm harness channel (U5)", "M3 standoffs 5 × 5 mm, 3–50 mm long (Addendum 2.3)",
                            ("every part except the PC/104 stack (anchored at its end plate) shifted along Z toward "
                             "a centred COM (at least into the CDS box), within the end plates and never at the "
                             "cost of a mount")]}

    def item_mesh(self, iid: str) -> bytes:
        lid, _, _ = iid.rpartition("-")
        e = self.archive.get(lid)
        if e is not None and e.meta.get("mfg_items") is not None:
            it = next((x for x in e.meta["mfg_items"] if x["id"] == iid), None)
            p = self.store.cache / "items" / lid / f"{iid}.bin" if it is not None else None
            if p is None or not p.is_file():
                raise KeyError(iid)
            return p.read_bytes()
        lid, _, k = iid.rpartition("-br")
        e = self.archive.get(lid)
        if e is not None and k.isdigit() and int(k) < len(e.meta.get("brackets") or []):
            return self._bracket_mesh(e, int(k))
        lid, _, k = iid.rpartition("-rod")
        e = self.archive.get(lid)
        if e is not None and k.isdigit() and int(k) < len(e.meta.get("stack_hardware") or []):
            boxes = dict(self._rod_boxes(e))                 # the rod's keep-out column (search and proof)
            b = boxes.get(e.meta["stack_hardware"][int(k)]["name"])
            if b is None:
                raise KeyError(iid)
            return self._rod_mesh(np.asarray(b, float), self._stack_board_z(e))
        lid, _, k = iid.rpartition("-so")
        e = self.archive.get(lid)
        if e is None or not k.isdigit() or int(k) >= len(e.meta.get("standoffs") or []):
            raise KeyError(iid)
        return self._box_mesh(np.asarray(e.meta["standoffs"][int(k)][1], float))

    def _designed_item(self, iid: str) -> tuple[LayoutEntry, int, dict, Path | None]:
        """A designed bracket's layout, index, design record and its colour-map file (None when the design has none:
        designed before the maps were saved, or no solid). KeyError when the item is not a designed bracket."""
        lid, _, k = iid.rpartition("-br")
        e = self.archive.get(lid)
        if e is None or not k.isdigit() or int(k) >= len((e.meta or {}).get("brackets") or []):
            raise KeyError(iid)
        b = e.meta["brackets"][int(k)]
        d = (e.meta.get("bracket_designs") or {}).get(b["pid"]) or {}
        if d.get("mass_kg") is None:
            raise KeyError(iid)
        p = self.store.cache / "items" / e.id / str(d["fea_file"]) if d.get("fea_file") else None
        return e, int(k), d, (p if p is not None and p.is_file() else None)

    def item_fea(self, iid: str) -> dict:
        """What the colour maps of a designed bracket show (gd.evaluate.display_fields): the fields with their units and
        maxima, the launch environment, the material and its allowables; `available` false when the design has no
        maps yet (designed before they were saved: redesign it)."""
        e, _, d, p = self._designed_item(iid)
        info = dict(d.get("fea_view") or {})
        info.update(item_id=iid, layout_id=e.id, part_id=d.get("pid"), available=p is not None and bool(info.get("fields")),
                    passed=d.get("passed"), governing=d.get("governing"), ms_yield=d.get("ms_yield"),
                    ms_ult=d.get("ms_ult"), ms_bolt=d.get("ms_bolt"), f1_hz=d.get("f1_hz"))
        if not info["available"]:
            info["why"] = info.get("error") or ("no colour maps for this design: it was designed before they were saved "
                                                "— redesign it in the Mounting Hardware tab")
        return jsonable(info)

    def item_fea_field(self, iid: str, field_id: str) -> bytes:
        """One colour-map field of a designed bracket: float32 little-endian, one value per vertex of its mesh
        (GET /api/items/{iid}/mesh)."""
        _, _, _, p = self._designed_item(iid)
        if p is None:
            raise KeyError(iid)
        with np.load(p) as z:
            if field_id not in z.files:
                raise KeyError(field_id)
            return np.asarray(z[field_id], "<f4").tobytes()

    def _stack_board_z(self, e: LayoutEntry) -> list[tuple[float, float]]:
        """z extent (mm) of each PC/104 board of the layout, lowest first."""
        ids = set((e.meta or {}).get("stack_ids") or [])
        if not ids:
            return []
        recs = self.layout_records(e)
        out = []
        for pid, o, t in e.poses:
            if pid in ids and pid in recs:
                r = recs[pid]
                z = to_world(r.v[r.hull.vertex_ids], o, np.asarray(t, float))[:, 2]
                out.append((float(z.min()), float(z.max())))
        return sorted(out)

    @staticmethod
    def _cylinder(cx: float, cy: float, z0: float, z1: float, r: float, n: int = 16) -> tuple[np.ndarray, np.ndarray]:
        """A closed cylinder along z (n sides; side and caps with their own vertices, so the side shades round and the
        caps flat), outward-facing triangles."""
        a = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
        ring = np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])
        lo, hi = np.column_stack([ring, np.full(n, z0)]), np.column_stack([ring, np.full(n, z1)])
        v = np.vstack([lo, hi, lo, hi, [[cx, cy, z0], [cx, cy, z1]]])
        f = []
        for i in range(n):
            j = (i + 1) % n
            f += [[i, j, n + j], [i, n + j, n + i], [4 * n, 2 * n + j, 2 * n + i], [4 * n + 1, 3 * n + i, 3 * n + j]]
        return v, np.asarray(f, np.int64)

    @classmethod
    def _rod_mesh(cls, b: np.ndarray, boards: list[tuple[float, float]]) -> bytes:
        """A PC/104 rod as the hardware it stands for: the M3 rod over the whole length, through the boards' corner
        mounting holes, and the 5 mm spacer tubes only where the boards leave it free (from the end plate to the first
        board, between boards). `b` is the rod's keep-out column, which stays the full 5 mm everywhere in the search and
        the proof (nothing else may enter it); `boards` their z extents."""
        from ..constraints.stage2_model import ROD_DIAMETER
        cx, cy, z0, z1 = 0.5 * (b[0] + b[3]), 0.5 * (b[1] + b[4]), float(b[2]), float(b[5])
        gaps, cur = [], z0
        for lo, hi in boards:
            lo, hi = max(lo, z0), min(hi, z1)
            if hi <= lo:
                continue
            if lo > cur + 1e-9:
                gaps.append((cur, lo))
            cur = max(cur, hi)
        if z1 > cur + 1e-9:
            gaps.append((cur, z1))
        pieces = [cls._cylinder(cx, cy, z0, z1, ROD_DIAMETER / 2.0)]
        pieces += [cls._cylinder(cx, cy, a, c, s2.ROD_KEEP / 2.0) for a, c in gaps]
        vs, fs, n = [], [], 0
        for v, f in pieces:
            vs.append(v)
            fs.append(f + n)
            n += len(v)
        v, f = np.vstack(vs).astype("<f4"), np.vstack(fs).astype("<u4")
        return np.array([len(v), len(f)], "<u4").tobytes() + v.tobytes() + f.tobytes()

    @staticmethod
    def _box_mesh(b: np.ndarray) -> bytes:
        """An axis-aligned box (lo xyz, hi xyz) as the viewers' mesh format."""
        v = np.array([[x, y, z] for z in (b[2], b[5]) for y in (b[1], b[4]) for x in (b[0], b[3])], "<f4")
        f = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                      [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]], "<u4")
        return np.array([len(v), len(f)], "<u4").tobytes() + v.tobytes() + f.tobytes()

    def _bracket_mesh(self, e: LayoutEntry, k: int) -> bytes:
        """A V2 bracket's mesh: the designed solid when the bracket design job has built one, else the solid built
        inside its reserved box (an estimate's box for a cradle or metal-AM bracket)."""
        from ..mfg.brackets import v2_bracket
        b = e.meta["brackets"][k]
        p = self.store.cache / "items" / e.id / f"{e.id}-br{k}.bin"
        d = (e.meta.get("bracket_designs") or {}).get(b["pid"]) or {}
        if d.get("mass_kg") is not None and p.is_file():   # a redesign without a solid leaves an older file behind
            return p.read_bytes()
        br = v2_bracket(b["name"], b["pid"], b)
        vs, fs, n = [], [], 0
        for v, f in br.meshes:
            vs.append(np.asarray(v, "<f4"))
            fs.append(np.asarray(f, np.int64) + n)
            n += len(v)
        v, f = np.vstack(vs), np.vstack(fs).astype("<u4")
        return np.array([len(v), len(f)], "<u4").tobytes() + v.tobytes() + f.tobytes()

    def _candidate_json(self, h, poses, raw, g, nrm) -> dict:
        return jsonable({
            "id": f"C-{h[:8]}", "hash": h, "stage": self.ctx.stage, "mode": "default", "status": "CANDIDATE",
            **{k: self.store.revs[k] for k in ("parts_rev", "constraint_rev", "mass_rev", "weights_rev")},
            "poses": self.pose_json(poses), "extra_items": [],
            "metrics": {"length_used_mm": raw.get("L"), "com_mm": raw.get("com"), "com_error_mm": raw.get("D"),
                        "trace_kgm2": raw.get("T")},
            "scores": {"normalised": nrm, "g": g, "norm_epoch": self._norm().epoch},
            "algorithm": ALGORITHM, "validation": None, "origin": "search", "created": now_iso(),
        })

    def envelope(self, client: Client | None, type_: str, payload) -> str:
        if client is not None:
            client.seq += 1
        return json.dumps({"v": 1, "type": type_, "seq": client.seq if client else 0, **self.revs,
                           "applied_client_seq": client.applied if client else 0, "ts": now_iso(),
                           "payload": jsonable(payload)}, allow_nan=False)

    def send(self, client: Client, type_: str, payload) -> None:
        try:
            client.queue.put_nowait(self.envelope(client, type_, payload))
        except asyncio.QueueFull:
            pass

    def broadcast(self, type_: str, payload, only=None) -> None:
        if not self.clients:
            return
        payload = jsonable(payload)
        for c in list(self.clients):
            if only is not None and not only(c):
                continue
            if type_ in ("progress", "layout.candidate") and c.queue.qsize() > 200:
                continue                       # a slow client skips transient messages, never results
            self.send(c, type_, payload)

    # =========================================================================================== snapshots
    def project_json(self) -> dict:
        lo, hi = s2.inner_box()
        spec = s2.stage2_spec(stage2_config(self._active_records()))
        frame_boxes = [{"kind": s.kind, "id": s.name, "min": s.corners.min(0).tolist(), "max": s.corners.max(0).tolist()}
                       for s in spec.statics]
        fm, fc, _ = s2.frame_mass_props()
        building = [{"id": pid, "units": u} for (pid, u), f in self.builds.items() if not f.done()]
        ff = formfactor.info()
        return jsonable({
            "name": self.store.name,
            "enclosure": {"size_mm": list(ff["envelope_mm"]), "min_mm": ENCLOSURE_LO.tolist(), "max_mm": ENCLOSURE_HI.tolist(),
                          "form": f"{ff['name']} CubeSat, CDS Rev 14.1 envelope ({ff['drawing']})",
                          "form_factor": ff["name"], "options": list(formfactor.FORM_FACTORS)},
            "rotations": [np.asarray(m).reshape(3, 3).tolist() for m in as_lists()],
            "parts": self.part_list(),
            "settings": self.store.settings,
            "stage2_frame": {"status": "ASSUMED", "wall_mm": s2.WALL, "inner_box_mm": (hi - lo).tolist(),
                             "rail_mm": [s2.RAIL, s2.RAIL], "boxes": frame_boxes,
                             "walls": {"inner_min": lo.tolist(), "inner_max": hi.tolist()},
                             "frame_mass_kg": fm, "frame_com_mm": fc.tolist(),
                             "note": "harness channel interrupted across the PCB stack (U5 default); the PCB stack "
                                     "hangs on four rods with spacer tubes from its end plate (v2.5)"},
            "limits": {"com_box_mm": list(ff["com_box_mm"]), "cds_mass_note_kg": ff["mass_note_kg"],
                       "clearance_part_mm": s2.C_PP, "clearance_wall_mm": s2.C_WALL,
                       "length_mm": float(ff["envelope_mm"][2]), "cable_mode_threshold": 70},
            "revs": self.revs,
            "dataset_sha256": self.store.dataset_sha256,
            "building": building,
            "bounds": {"cpsat_single_box": self.cpsat_results.get(self.ctx.parts_sig) if self.ctx else None},
            "inbox": str(self.store.inbox),
            "fusion360": "NOT_CONFIGURED",
        })

    def snapshot(self) -> dict:
        best = self.archive.get(self.best_id) if self.best_id else None
        least = self.archive.get(self.least_id) if self.least_id else None
        return {"project": self.project_json(), "best_validated": self.layout_json(best) if best else None,
                "candidate": self.candidate, "run_status": self.run_status, "selector": self.selector(),
                "least_violating": self.layout_json(least) if least else None,
                "progress": self._progress()}       # the running time also while paused (no progress messages then)

    def selector(self) -> dict:
        c = self.choice or (self._compute_choice() if self.ctx is not None else None)
        if c is None:
            return {"algorithm": None, "reasons": ["no packable parts yet"], "evidence": []}
        d = c.to_json()
        islands = [w for w in self.workers if w.role == "island"]
        d["islands"] = [{"id": w.id, **(w.plan or {}), "running": w.info} for w in islands]
        d["pending"] = self.choice_pending[0].id if self.choice_pending else None
        d["log"] = self.selector_log[-20:]
        d["part_stats"] = {"n_parts": self._part_stats().n_parts, "box_overhead": self._part_stats().box_overhead,
                           "volume_shares": self._part_stats().shares}
        return jsonable(d)

    def selector_sweep(self, slider: str) -> dict:
        s = self.store.settings
        if slider not in s["sliders"]:
            raise ValueError(f"unknown slider {slider!r}")
        out = sweep(int(s["stage"]), s["sliders"], self._part_stats(), slider, self._mode(), self.evidence or None)
        out["current"] = s["sliders"][slider]
        out["rule"] = (f"benchmark evidence ({self.evidence_source})" if self.evidence
                       else "default rule — no benchmark evidence yet")
        return out

    def selector_map(self, x: str, y: str, n: int) -> dict:
        s = self.store.settings
        for k in (x, y):
            if k not in s["sliders"]:
                raise ValueError(f"unknown slider {k!r}")
        out = grid_map(int(s["stage"]), s["sliders"], self._part_stats(), x, y, max(2, min(int(n), 101)), self._mode(),
                       self.evidence or None)
        out["current"] = [s["sliders"][x], s["sliders"][y]]
        return out

    # =========================================================================================== idea map
    def ideamap(self) -> dict:
        """Addendum 3.2a: node-link graph from live state; every edge carries the quantity behind the decision."""
        nodes, edges = [], []

        def node(i, label, kind, tab=None, detail=None):
            nodes.append({"id": i, "label": label, "kind": kind, "tab": tab, "detail": detail})

        def edge(a, b, label=None):
            edges.append({"from": a, "to": b, "label": label})
        recs = self._active_records()
        stats = self._part_stats() if recs else None
        s = self.store.settings
        node("parts", f"{len(recs)} parts", "input", "components",
             f"total solid volume {sum((r.volume_mm3 or 0) for r in recs.values()) / 1e3:.1f} cm³")
        groups = {"box-like": [], "convex": [], "curved": [], "concave": [], "through-hole": []}
        for pid, r in recs.items():
            for g in groups:
                if any(lab.startswith(g) or (g == "concave" and "concave" in lab) for lab in r.labels):
                    groups[g].append(r.name)
        for g, names in groups.items():
            if not names:
                continue
            share = stats.shares.get(g, 0.0) if stats else 0.0
            node(f"grp:{g}", f"{g} ({len(names)})", "classification", "components", ", ".join(names))
            edge("parts", f"grp:{g}", f"{100 * share:.0f} % of the volume")
        node("proxy:boxes", "certified compound boxes", "proxy", "components",
             f"box proxies over-cover the solids by {100 * stats.box_overhead:.0f} %" if stats else None)
        node("proxy:cover", "certified convex covers", "proxy", "components", "used by the validator (G3)")
        node("proxy:mesh", "full meshes", "proxy", "components", "validator G4 and the height-map decoder")
        for g in groups:
            if groups[g]:
                edge(f"grp:{g}", "proxy:boxes" if g in ("box-like", "convex") else "proxy:cover")
        w = slider_weights(s["sliders"], int(s["stage"]), "default")
        for k, label in (("L", "compactness"), ("D", "balance (COM)"), ("I", "rotational inertia"),
                         ("G", "feasibility margin"), ("H", "cable path"), ("C", "hardware cost"),
                         ("O", "optional parts included")):
            if k in w:
                node(f"w:{k}", f"{label}", "objective", "optimization", f"weight {w[k]:.2f}")
        node("stage", f"Stage {s['stage']} {'IDEALIZED' if int(s['stage']) == 1 else 'ENGINEERING-CONSTRAINED'}",
             "constraint", "engineering",
             "containment and non-interpenetration" if int(s["stage"]) == 1 else
             f"walls, rails, 2.2 / 1.2 mm clearances, PC/104 stack, mounting, COM box; cable mode: {self._stage2_mode()}")
        locks = [r.name for r in recs.values() if r.locked]
        if locks:
            node("locks", f"{len(locks)} locked part(s)", "constraint", "components", ", ".join(locks))
        for aid, lab in ALGORITHMS.items():
            if aid == "box_constructive":
                continue
            node(f"alg:{aid}", lab, "algorithm", "comparison")
            edge("proxy:boxes" if aid != "hybrid_heightmap" else "proxy:mesh", f"alg:{aid}")
        node("alg:cpsat_box", "CP-SAT on single-box proxies", "algorithm", "comparison",
             (lambda c: f"{c.get('status')}, length {c.get('length_mm')} mm, bound {c.get('lower_bound_mm')} mm "
                        "(single-box proxies only)")(self.cpsat_results.get(self.ctx.parts_sig, {}))
             if self.ctx else None)
        c = self.choice
        if c is not None:
            node("choice", f"chosen: {c.label}", "decision", "explain", c.reasons[0] if c.reasons else None)
            if c.id in ALGORITHMS:
                edge(f"alg:{c.id}", "choice", "default rule" if c.rule == "default" else "benchmark evidence")
            for k in w:
                edge(f"w:{k}", "choice", f"weight {w[k]:.2f}")
            edge("stage", "choice", f"Stage {s['stage']}")
            if stats:
                edge("proxy:boxes", "choice", f"box overhead {100 * stats.box_overhead:.0f} %")
        best = self.archive.get(self.best_id) if self.best_id else None
        least = self.archive.get(self.least_id) if self.least_id else None
        show = best or least
        if show is not None:
            m = show.metrics
            node("layout", f"{show.id} {show.status}", "result", "overview",
                 f"length {m.get('length_used_mm', 0):.1f} mm, COM error {m.get('com_error_mm') or 0:.1f} mm, "
                 f"λmax {m.get('lambda_max_kgm2') or 0:.3e} kg·m²")
            edge("choice", "layout", show.algorithm.get("detail") or show.algorithm.get("label"))
            node("proof", "fit proof", "proof", "explain", "theorem + lemmas, certificate JSON, stand-alone checker")
            edge("layout", "proof", f"{show.validation.get('pairs', 0)} pairs certified")
        return jsonable({"nodes": nodes, "edges": edges, "generated": now_iso()})

    # =========================================================================================== M8 studies
    BENCH_DIR = Path(__file__).resolve().parents[4] / "data" / "runs" / "benchmarks"

    def _latest_benchmark(self) -> Path | None:
        if not self.BENCH_DIR.exists():
            return None
        files = sorted(self.BENCH_DIR.glob("*/benchmarks.json"), key=lambda p: p.stat().st_mtime)
        return files[-1] if files else None

    def _load_evidence(self) -> None:
        if not getattr(self, "use_evidence", True):
            return
        p = self._latest_benchmark()
        if p is None:
            return
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.evidence = d.get("evidence", [])
        self.evidence_source = f"{p.parent.name}, {d.get('seeds')} seeds, budget {d.get('budget')}"

    def benchmarks(self, instance: str | None = None, preset: str | None = None) -> dict | None:
        live = self.studies.get("benchmark")
        if live and live["proc"].is_alive():
            prog = self._study_progress("benchmark")
            return {"status": "RUNNING", "progress": prog, "rows": []}
        p = self._latest_benchmark()
        if p is None:
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        blocks = sorted({f"{r['instance']}|{r['preset']}" for r in d.get("rows", [])})
        want = f"{instance or 'I1'}|{preset or 'balanced'}"
        if want not in blocks and blocks:
            want = blocks[0]
        inst, pre = want.split("|")
        rows = [r for r in d["rows"] if r["instance"] == inst and r["preset"] == pre]
        curves = {k.split("|")[2]: v for k, v in d.get("curves", {}).items() if k.startswith(want + "|")}
        return {**{k: v for k, v in d.items() if k not in ("rows", "curves")}, "rows": rows, "curves": curves,
                "block": {"instance": inst, "preset": pre}, "blocks": blocks, "source": str(p.parent.name),
                "summary": [s for s in d.get("summary", []) if s["instance"] == inst and s["preset"] == pre],
                "tests": [t for t in d.get("tests", []) if t["instance"] == inst and t["preset"] == pre]}

    def start_benchmarks(self, opts: dict) -> dict:
        from datetime import datetime as _dt, timezone as _tz
        cur = self.studies.get("benchmark")
        if cur and cur["proc"].is_alive():
            raise ValueError("a benchmark run is already in progress")
        out = self.BENCH_DIR / _dt.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
        out.mkdir(parents=True, exist_ok=True)
        # not daemonic: the study runs its own worker pool (terminated explicitly in stop())
        proc = mp.get_context("spawn").Process(target=_bench_main, args=(str(out), dict(opts)), daemon=False)
        proc.start()
        self.studies["benchmark"] = {"proc": proc, "path": out / "progress.json", "mtime": None, "out": out}
        return {"status": "RUNNING", "folder": str(out)}

    def _size_path(self) -> Path:
        return self.store.cache / f"size_study_{self.ctx.parts_sig if self.ctx else 'none'}.json"

    def size_study(self) -> dict | None:
        p = self._size_path()
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        live = self.studies.get("size")
        if d.get("status") == "RUNNING" and not (live and live["proc"].is_alive()):
            d["status"], d["stop_reason"] = "STOPPED", d.get("stop_reason") or "stopped (process ended)"
        return d

    def start_size_study(self, opts: dict) -> dict:
        import pickle
        from ..bench.size_study import size_study_main
        if self.ctx is None:
            raise ValueError("no packable parts")
        cur = self.studies.get("size")
        if cur and cur["proc"].is_alive():
            raise ValueError("a Size Study is already running")
        snap = self.store.cache / f"size_records_{self.ctx.parts_sig}.pkl"
        snap.write_bytes(pickle.dumps(self._active_records(), protocol=pickle.HIGHEST_PROTOCOL))
        path = self._size_path()
        allowed = {"stages", "seeds", "budget0", "max_hours", "workers", "preset", "conv_minutes",
                   "min_minutes_per_combo", "step", "tol"}
        o = {k: v for k, v in (opts or {}).items() if k in allowed}
        o.setdefault("workers", max(2, 12 - len(self.workers) - 1))
        proc = mp.get_context("spawn").Process(target=size_study_main, args=(str(snap), str(path), o), daemon=False)
        proc.start()
        self.studies["size"] = {"proc": proc, "path": path, "mtime": None}
        return {"status": "RUNNING", "workers": o["workers"]}

    def stop_study(self, name: str) -> bool:
        s = self.studies.get(name)
        if not s or not s["proc"].is_alive():
            return False
        _kill_tree(s["proc"].pid)                  # the study and its worker pool
        s["proc"].terminate()
        if name == "size" and s["path"].exists():
            try:
                d = json.loads(s["path"].read_text(encoding="utf-8"))
                d["status"], d["stop_reason"] = "STOPPED", "stopped by the user"
                atomic_write_text(s["path"], json.dumps(d, indent=1))
            except (OSError, json.JSONDecodeError):
                pass
        return True

    def _study_progress(self, name: str) -> float | None:
        s = self.studies.get(name)
        if not s or not s["path"].exists():
            return None
        try:
            return float(json.loads(s["path"].read_text(encoding="utf-8")).get("progress") or 0.0)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _poll_studies(self) -> None:
        for name, s in list(self.studies.items()):
            p = s["path"]
            if p.exists():
                m = p.stat().st_mtime
                if m != s["mtime"]:
                    s["mtime"] = m
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        d = {}
                    self.broadcast("study.update", {"study": name, "progress": d.get("progress"),
                                                    "partial": {"status": d.get("status"), "phase": d.get("phase")}})
            if name == "benchmark" and not s["proc"].is_alive() and not s.get("done"):
                s["done"] = True
                self._load_evidence()
                self.broadcast("study.update", {"study": "benchmark", "progress": 1.0, "partial": {"status": "DONE"}})
                if self.ctx is not None:
                    self.choice_pending = (self._compute_choice(), 0.0)

    def pareto(self) -> dict:
        """The non-dominated VALIDATED / FINAL layouts of the current inputs in (L̂, D̂, Î) — every layout of them
        counts, in memory or not — from the incremental front (_display_front) instead of the N × N comparison."""
        d = self._display_front() if self.ctx is not None else None
        pts = []
        for lid in (d["front"].ids if d is not None else []):
            raw = d["raw"][lid]
            g, nrm = self._score_raw(raw)
            pts.append({"layout_id": lid, "L": raw.get("L"), "D": raw.get("D"), "I": nrm["I"], "T": raw.get("T"),
                        "P": raw.get("P"), "L_norm": nrm["L"], "D_norm": nrm["D"], "g": g})
        hv = None
        if pts:
            try:
                import moocore
                arr = np.array([[p["L_norm"], p["D_norm"], p["I"]] for p in pts], float)
                hv = float(moocore.hypervolume(arr, ref=np.array([1.1, 1.1, 1.1])))
            except Exception:  # noqa: BLE001
                hv = None
        return jsonable({"points": pts, "hv": hv, "norm_epoch": self._norm().epoch})

    # =========================================================================================== archive I/O
    def _persist(self, e: LayoutEntry, row: bool = True) -> None:
        """Append the layout to archive.jsonl (its last line wins) and, with row, update its objective row."""
        self.archive.append(e)
        fam = (e.stage, e.parts_sig, e.spec_sig)
        self._fam_ver[fam] = self._fam_ver.get(fam, 0) + 1
        if row:
            self._table_put(e)

    def _load_archive(self) -> None:
        """Index archive.jsonl (layouts are read back when needed: service/archive.py) and compact it when at least
        200 lines, and a fifth of all its lines, are superseded by later lines of the same layout (designed brackets,
        FINAL)."""
        self.archive = LayoutArchive(self.store.archive_path, LayoutEntry.from_store, on_load=self._hydrate)
        self.archive.scan(self.by_hash)
        if self.archive.should_compact():
            self.archive.rewrite()
        # the layout counter is saved with the project only now and then, the archive with every layout: after the
        # server was stopped the counter can lag behind, and new layouts would reuse ids and shadow archived ones
        top = max((int(k[2:]) for k in self.archive if k.startswith("L-") and k[2:].isdigit()), default=0)
        if top > int(self.store.counters.get("layout", 0)):
            self.store.counters["layout"] = top

    # =========================================================================================== edits
    def apply_settings(self, new: dict) -> None:
        design = self._check_design_settings(new)    # before anything changes (ValueError: unknown preset or material)
        s = self.store.settings
        before = self._settings_view()
        old_stage = int(s.get("stage", 1))
        old_target = list(s.get("target_com_mm", [0, 0, 0]))
        old_s2 = self._stage2_mode()
        old_scale = self.part_scale()
        old_am = self._am_level()
        old_ff = s.get("form_factor", formfactor.DEFAULT)
        for k in ("stage", "target_com_mm", "compactness_definition", "show_frame_mass_in_com"):
            if k in new and new[k] is not None:
                s[k] = new[k]
        if new.get("form_factor") in formfactor.FORM_FACTORS:
            s["form_factor"] = new["form_factor"]
        if new.get("part_scale_pct") is not None:
            s["part_scale_pct"] = float(np.clip(float(new["part_scale_pct"]), 50.0, 100.0))
        if new.get("auto_design_brackets") is not None:
            s["auto_design_brackets"] = bool(new["auto_design_brackets"])
        old_design = self._design_defaults()
        s.update(design)
        if "sliders" in new and isinstance(new["sliders"], dict):
            for k, v in new["sliders"].items():
                if k in s["sliders"] and v is not None:
                    s["sliders"][k] = float(np.clip(float(v), 0, 100))
        s["stage"] = 2 if int(s.get("stage", 1)) == 2 else 1
        after = self._settings_view()
        if after == before:
            # nothing the search depends on moved (the launch environment, the bracket material, the automatic design
            # switch, a display option, the speed/quality slider): no re-scoring, so the best layout stays the one
            # whose brackets were designed (a re-score can rank another first: its designed masses changed its score)
            self.store.save()
        else:
            self._apply_search_settings(before, after, old_stage, old_target, old_s2, old_scale, old_am, old_ff)
        # a running search goes on with the new settings; a paused one stays paused (Pause is the only stop). Another
        # launch environment or default material: the best layout's brackets designed for the old ones are designed
        # again (_maybe_auto_design), as after a pause
        if self.run_status == "PAUSED" and (new.get("auto_design_brackets") or self._design_defaults() != old_design):
            self._maybe_auto_design()

    def _apply_search_settings(self, before: dict, after: dict, old_stage, old_target, old_s2, old_scale, old_am,
                               old_ff) -> None:
        """A setting the search depends on moved (apply_settings): new inputs and a new search, or a re-score."""
        s = self.store.settings
        # V2: the saved bracket STL files belong to the layout found at the old settings; the automatic bracket
        # design and STL save wait until the slider has stopped moving (_tick)
        self._drop_saved_brackets(settings_change_text(before, after))
        self._settle_at = time.monotonic() + SETTINGS_SETTLE_S
        self._bump("weights_rev")
        if s.get("form_factor", formfactor.DEFAULT) != old_ff:
            # V2 form factor: another envelope and COM box — new context, new search, project re-sent
            self._refresh_inputs(f"form factor {s['form_factor']}", bump_parts=True)
            self.broadcast("project.changed", {"reason": f"form factor {s['form_factor']}"})
        elif int(s["stage"]) != old_stage:
            self._refresh_inputs(f"stage {s['stage']} selected", bump_parts=False)
        elif int(s["stage"]) == 2 and self._stage2_mode() != old_s2:
            # the cable-routing slider crossed a mode boundary (0 / 1–69 / ≥ 70): different rules, new islands
            self._refresh_inputs(f"cable routing: {self._stage2_mode()} mode", bump_parts=False)
        elif self.part_scale() != old_scale:
            # V2 part-size slider: scaled parts are other parts (new context, new search)
            self._refresh_inputs(f"part size {100 * self.part_scale():.0f} %", bump_parts=True)
        elif int(s["stage"]) == 2 and self._am_level() != old_am:
            # V2 bracket budget crossed a step (0 / 34 / 67 / 100): another metal-AM preference — different
            # bracket choices, new islands
            self._refresh_inputs("bracket budget: " + AM_LEVEL_TEXT[self._am_level()], bump_parts=False)
        else:
            if list(s.get("target_com_mm", [0, 0, 0])) != old_target and self.ev is not None:
                self.ev.target = np.asarray(self._target(), float)
                for w in self.workers:
                    if w.role == "island" and self.ctx is not None:
                        w.cmd_q.put(("phys", self.ctx.ctx_id, self.store.revs["mass_rev"], self._phys_wire(),
                                     self._target()))
            self._restamp_and_rescore()             # a new COM target: the table key changes, physics recomputed
            self._publish_best("archive")
            if self.ctx is not None:
                nc = self._compute_choice()
                if self.choice is not None and nc.id != self.choice.id:
                    # the islands switch only once the choice has been stable for a moment (slider drags)
                    self.choice_pending = (nc, time.monotonic())
                else:
                    self.choice_pending = None
                    old_reasons = self.choice.reasons if self.choice else None
                    self.choice = nc
                    if nc.reasons != old_reasons:
                        self.broadcast("selector.changed", self.selector())

    def lock_pose_for(self, pid: str) -> dict | None:
        if self.best_id is None:
            return None
        for p, o, t in self.archive[self.best_id].poses:
            if p == pid:
                return {"part_id": pid, "orient": int(o), "t_um": [int(round(v * 1000)) for v in t]}
        return None

    def apply_part_patch(self, pid: str, patch: dict) -> dict:
        e = self.store.entries.get(pid)
        if e is None:
            raise KeyError(pid)
        mass_changed = constraint_changed = False
        if "mass_kg" in patch:
            m = patch["mass_kg"]
            if m is not None and not (isinstance(m, (int, float)) and m > 0 and math.isfinite(m)):
                raise ValueError("mass_kg must be a positive number (kg) or null")
            e.mass_override_kg = None if m is None else float(m)
            mass_changed = True
        if "density_kg_m3" in patch:
            d = patch["density_kg_m3"]
            if d is None:
                e.density_kg_m3, e.density_user = 2700.0, False
            else:
                if not (isinstance(d, (int, float)) and d > 0 and math.isfinite(d)):
                    raise ValueError("density_kg_m3 must be a positive number")
                e.density_kg_m3, e.density_user = float(d), True
            e.mass_override_kg = None if "mass_kg" not in patch else e.mass_override_kg
            mass_changed = True
        if "locked" in patch:
            want = bool(patch["locked"])
            if want and not e.locked:
                lp = patch.get("lock_pose") or self.lock_pose_for(pid)
                if lp is None:
                    raise ValueError("cannot lock: the part is not in the current best validated layout")
                e.locked, e.lock_pose = True, lp
            elif not want:
                e.locked, e.lock_pose = False, None
            constraint_changed = True
        if "allowed_orients" in patch:
            ao = patch["allowed_orients"]
            e.allowed_override = None if not ao else [int(o) for o in ao if 0 <= int(o) < 24]
            constraint_changed = True
        if "tags" in patch:
            e.tags = [str(t) for t in (patch["tags"] or [])]
            e.tags_user = True
            constraint_changed = True
        if "subsystem" in patch:
            e.subsystem_override = str(patch["subsystem"]) if patch["subsystem"] else None
        self.store.save()
        rec = self.records.get(pid)
        if rec is not None:
            self.store.apply_entry(rec, e)
        if constraint_changed:
            self._refresh_inputs(f"constraints of {e.name} changed", bump_parts=False)
        elif mass_changed:
            self._bump("mass_rev")
            if self.ev is not None:
                self.ev.phys = self._phys(self._ctx_scale())
            for w in self.workers:
                if w.role == "island" and self.ctx is not None:
                    w.cmd_q.put(("phys", self.ctx.ctx_id, self.store.revs["mass_rev"], self._phys_wire(), self._target()))
            prev = self.best_id
            self._restamp_and_rescore()             # a new mass revision: the table key changes, physics recomputed
            if prev is not None and prev in self.archive:
                self.broadcast("metrics.update", {"layout_id": prev, "metrics": self.archive[prev].metrics})
            if self.best_id != prev:
                self._publish_best("archive")
        else:
            self._bump("parts_rev")
            self._restamp_and_rescore()
            self.broadcast("project.changed", {"reason": f"{e.name} updated"})
            self._publish_best("archive")
        return self.part_json(pid)

    def part_json(self, pid: str) -> dict:
        return next(p for p in self.part_list() if p["id"] == pid)

    def add_files(self, files: list[tuple[str, bytes]], units: str | None) -> list[dict]:
        new, errors = [], []
        for name, data in files:
            try:
                e = self.store.add_file(data, name, units)
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
                continue
            self.quick[e.id] = quick_inspect(data)
            self._start_build(e, e.units)
            new.append(e.id)
        if errors and not new:
            raise ValueError("; ".join(errors))
        self._bump("parts_rev")
        self.broadcast("project.changed", {"reason": f"added {len(new)} file(s)"})
        return [self.part_json(pid) for pid in new]

    async def confirm_units(self, pid: str, units: str) -> dict:
        e = self.store.entries.get(pid)
        if e is None:
            raise KeyError(pid)
        if units not in UNIT_TO_MM:
            raise ValueError(f"unknown units {units!r}")
        e.units, e.units_confirmed = units, True
        self.store.save()
        fut = self._start_build(e, units)
        try:
            await asyncio.shield(fut)
        except Exception:  # noqa: BLE001 - reported through build_errors
            pass
        rec = self.store.load_record(e)
        if rec is not None:
            self._set_record(rec)
            self._refresh_inputs(f"units of {e.name} confirmed ({units})")
            self._maybe_auto_ladder(e)
        return self.part_json(pid)

    # =========================================================================================== detail ladder
    def _ladder_path(self, e: PartEntry) -> Path:
        d = self.store.cache / "fidelity"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{e.sha256[:24]}_{e.units}.json"

    def _load_ladder(self, e: PartEntry) -> None:
        from ..fidelity.ladder import load_choice
        res, reps = load_choice(self._ladder_path(e))
        if res.get("status") == "DONE":
            self.reps[e.id] = reps

    def _maybe_auto_ladder(self, e: PartEntry) -> None:
        """Addendum 4: the ladder runs by itself for parts added later (not for the seeded dataset)."""
        if not self.auto_ladder or e.source == "dataset" or not e.units_confirmed:
            return
        if e.id in self.ladders and not self.ladders[e.id]["future"].done():
            return
        if self._ladder_path(e).exists():
            self._load_ladder(e)
            return
        self.start_ladders([e.id])

    def start_ladders(self, pids: list[str] | None = None, budget_s: float = 600.0) -> list[str]:
        import pickle
        from ..fidelity.ladder import ladder_job
        recs = self._active_records()
        pids = [p for p in (pids or list(recs)) if p in recs]
        if not pids:
            return []
        snap = self.store.cache / f"ladder_records_{self.ctx.parts_sig if self.ctx else 'x'}.pkl"
        snap.write_bytes(pickle.dumps(recs, protocol=pickle.HIGHEST_PROTOCOL))
        started = []
        for pid in pids:
            old = self.ladders.get(pid)
            if old is not None and not old["future"].done():
                continue
            e = self.store.entries[pid]
            path = self._ladder_path(e)
            for f in path.parent.glob(path.stem + "*"):
                f.unlink(missing_ok=True)
            fut = self.ladder_pool.submit(formfactor.call_with, formfactor.current(), ladder_job, str(snap), pid, dict(self.store.settings["sliders"]), str(path),
                                          float(budget_s), dict(self.ladder_opts))
            self.ladders[pid] = {"future": fut, "path": path, "mtime": None, "status": "PENDING", "progress": 0.0}
            self.reps.pop(pid, None)
            started.append(pid)
            self.broadcast("study.update", {"study": "fidelity", "progress": 0.0,
                                            "partial": {"part_id": pid, "status": "PENDING", "progress": 0.0}})
        return started

    def _poll_ladders(self) -> None:
        for pid, L in list(self.ladders.items()):
            p = L["path"]
            fut = L["future"]
            if fut.done() and fut.exception() is not None and L["status"] != "ERROR":
                L["status"] = "ERROR"
                self._error(f"detail ladder for {pid} failed: {fut.exception()!r}")
                continue
            if not p.exists():
                continue
            m = p.stat().st_mtime
            if m == L["mtime"]:
                continue
            L["mtime"] = m
            try:
                res = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            L["status"], L["progress"] = res.get("status", "RUNNING"), res.get("progress", 0.0)
            if L.get("study") == "mfg":                # finished through _on_mfg
                continue
            if L.get("study") == "free_rotation":
                self.broadcast("study.update", {"study": "free_rotation", "progress": 1.0 if L["status"] == "DONE" else 0.0,
                                                "partial": {"status": L["status"]}})
                continue
            if L.get("study") == "attribution":
                self.broadcast("study.update", {"study": "attribution", "progress": L["progress"],
                                                "partial": {"status": L["status"], "rows": len(res.get("rows", []))}})
                continue
            if L.get("study") == "largest_size":
                self.broadcast("study.update", {"study": "largest_size", "progress": L["progress"],
                                                "partial": {"status": L["status"], "largest_pct": res.get("largest_pct")}})
                continue
            if L.get("study") == "bracket_design":     # finished through _on_bracket_design
                if L["status"] != "DONE":
                    self.broadcast("study.update", {"study": "bracket_design", "progress": L["progress"],
                                                    "partial": self._design_progress(res, L["status"])})
                continue
            self.broadcast("study.update", {"study": "fidelity", "progress": L["progress"],
                                            "partial": {"part_id": pid, "status": L["status"], "progress": L["progress"],
                                                        "level": res.get("current_level")}})
            if L["status"] == "DONE":
                e = self.store.entries.get(pid)
                if e is not None:
                    self._load_ladder(e)
                    self._refresh_inputs(f"detail levels chosen for {e.name}", bump_parts=False)

    def fidelity(self, pid: str) -> dict | None:
        e = self.store.entries.get(pid)
        if e is None:
            raise KeyError(pid)
        L = self.ladders.get(pid)
        p = self._ladder_path(e)
        if p.exists():
            try:
                res = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                res = None
            if res is not None:
                res["in_use"] = (self.ctx.levels.get(pid) if self.ctx is not None else None)
                return res
        if L is not None and not L["future"].done():
            return {"status": "PENDING", "levels": [], "chosen": {}, "reasons": {}, "stop_reason": None,
                    "part_id": pid}
        return None

    # =========================================================================================== CP-SAT seed
    def _start_cpsat(self) -> None:
        """Protocol §D.4 step 1: a CP-SAT solution on single-box proxies (Stage 1, no locked parts). Its layout is
        validated like any other; its bound is valid for the single-box proxy problem only."""
        import pickle
        from ..bench.cpsat import cpsat_job
        ctx = self.ctx
        if not self.use_cpsat or ctx is None or ctx.stage != 1 or ctx.fixed or self.cpsat_pool is None:
            return
        if ctx.parts_sig in self.cpsat_results:
            return
        self.cpsat_results[ctx.parts_sig] = {"status": "RUNNING"}
        snap = self.store.cache / f"cpsat_records_{ctx.parts_sig}.pkl"
        snap.write_bytes(pickle.dumps(ctx.records, protocol=pickle.HIGHEST_PROTOCOL))
        fut = asyncio.wrap_future(self.cpsat_pool.submit(cpsat_job, str(snap), self.cpsat_time_s, 2, 0), loop=self.loop)
        sigs = (ctx.parts_sig, ctx.constraint_sig, ctx.stage, ctx.spec_sig)
        fut.add_done_callback(lambda f, c=ctx.ctx_id, s=sigs: self._on_cpsat(f, c, s))

    def _on_cpsat(self, fut, ctx_id: str, sigs) -> None:
        if fut.cancelled():
            return
        if fut.exception() is not None:
            self.cpsat_results[sigs[0]] = {"status": "ERROR", "detail": repr(fut.exception())}
            return
        r = fut.result()
        self.cpsat_results[sigs[0]] = {k: r.get(k) for k in ("status", "length_mm", "lower_bound_mm", "seconds",
                                                               "valid_for", "optimal", "grid_mm")}
        if not r.get("poses") or self.ctx is None or self.ctx.ctx_id != ctx_id:
            return
        poses = [(p, int(o), np.asarray(t, float)) for p, o, t in r["poses"]]
        raw, cv = self.ev.raw_from_poses(poses, [])
        g, _ = self._score_raw(raw)
        h = layout_hash(sigs[2], poses)
        if h in self.by_hash or h in self.pending_hashes:
            return
        algo = {"id": "cpsat_box", "label": "CP-SAT on single-box proxies",
                "reason": f"{r['status']} after {r['seconds']:.0f} s; minimises the used length only",
                "search": "cp-sat", "decoder": "single-box proxy", "detail": "CP-SAT (OR-Tools) on single-box proxies",
                "lower_bound_mm": r.get("lower_bound_mm")}
        self.pending_hashes.add(h)
        self.val_queue.append({"key": (-1.0, g), "g": g, "cv": cv, "h": h, "poses": poses, "raw": raw, "keys": None,
                               "ctx_id": ctx_id, "sigs": sigs, "algo": algo, "compact": False, "meta": None,
                               "kind": "cpsat"})
        self._dispatch_validation()

    # =========================================================================================== Manufacturable Design
    def _mfg_dir(self) -> Path:
        return self.store.cache / "mfg" / (self.ctx.parts_sig if self.ctx else "none")

    def start_mfg(self, opts: dict | None = None) -> dict:
        import pickle
        from ..mfg.design import mfg_job
        if self.ctx is None:
            raise ValueError("no packable parts")
        L = self.ladders.get("__mfg__")
        if L is not None and not L.get("finalised"):
            raise ValueError("a Manufacturable Design run is already in progress")
        recs = {pid: self.rec_at(pid, self._ctx_scale()) for pid in self._active_records()}   # at the part size
        snap = self.store.cache / f"mfg_records_{self.ctx.parts_sig}.pkl"
        snap.write_bytes(pickle.dumps(recs, protocol=pickle.HIGHEST_PROTOCOL))
        out = self._mfg_dir()
        (out / "mfg.json").unlink(missing_ok=True)
        budget = float((opts or {}).get("budget_s", self.mfg_budget_s))
        mode = self._stage2_mode()
        fut = self.ladder_pool.submit(formfactor.call_with, formfactor.current(), mfg_job, str(snap), mode, dict(self.store.settings["sliders"]), str(out), budget)
        self.ladders["__mfg__"] = {"future": fut, "path": out / "mfg.json", "mtime": None, "status": "PENDING",
                                   "progress": 0.0, "study": "mfg"}
        wf = asyncio.wrap_future(fut, loop=self.loop)
        wf.add_done_callback(lambda f, o=out, s=self.ctx.parts_sig: self._on_mfg(f, o, s))
        self.broadcast("study.update", {"study": "mfg", "progress": 0.0, "partial": {"status": "RUNNING"}})
        return {"status": "RUNNING", "mode": mode, "budget_s": budget}

    def _on_mfg(self, fut, out: Path, parts_sig: str) -> None:
        L = self.ladders.get("__mfg__")
        try:
            self._finish_mfg(fut, out, parts_sig)
        except Exception as exc:  # noqa: BLE001
            if L is not None:
                L["error"] = repr(exc)
            self._error(f"Manufacturable Design could not be archived: {exc!r}")
        finally:
            if L is not None:
                L["finalised"] = True

    def _finish_mfg(self, fut, out: Path, parts_sig: str) -> None:
        import pickle
        L = self.ladders.get("__mfg__")
        if fut.cancelled():
            return
        if fut.exception() is not None:
            L["error"] = repr(fut.exception())
            self._error(f"Manufacturable Design failed: {fut.exception()!r}")
            return
        res = json.loads((out / "mfg.json").read_text(encoding="utf-8"))
        lay = pickle.loads((out / "layout.pkl").read_bytes())
        if self.ctx is None or self.ctx.parts_sig != parts_sig:
            return
        n = self.store.next_id("layout")
        lid = f"L-{n:04d}"
        meta = dict(lay["meta"] or {})
        hw = []
        items = []
        idir = self.store.cache / "items" / lid
        idir.mkdir(parents=True, exist_ok=True)
        for b in lay["brackets"]:
            hw.append((b.mass_kg, np.asarray(b.com_mm).tolist(), np.asarray(b.inertia_kgm2).tolist()))
            iid = f"{lid}-{b.id}"
            v = np.vstack([m[0] for m in b.meshes]).astype("<f4")
            offs = np.cumsum([0] + [len(m[0]) for m in b.meshes[:-1]])
            f = np.vstack([np.asarray(m[1]) + o for m, o in zip(b.meshes, offs)]).astype("<u4")
            (idir / f"{iid}.bin").write_bytes(np.array([len(v), len(f)], "<u4").tobytes() + v.tobytes() + f.tobytes())
            items.append({"id": iid, "kind": "bracket" if b.process not in ("direct", "standoff") else b.process,
                          "process": b.process, "for_part": b.for_part, "mesh_url": f"/api/items/{iid}/mesh",
                          "mass_kg": b.mass_kg, "cost_rel": b.cost_rel, "material": b.material,
                          "label": b.label or b.mount_type, "mount_type": b.mount_type})
        meta["hardware"] = hw
        meta["mfg_items"] = items
        meta["hardware_cost_rel"] = res["total_cost_rel"]
        poses = [(p, int(o), np.asarray(t, float)) for p, o, t in lay["poses"]]
        summary = {"valid": bool(lay["validation"]), "min_clearance_mm": lay["min_clearance_mm"], "levels": lay["levels"],
                   "violations": res["validation"]["violations"], "pairs": lay["pairs"], "statics": lay["statics"],
                   "seconds": res["seconds"], "validator_version": "1.0"}
        scale = self._sig_scale.get(parts_sig, 1.0)
        geo = self._geo_metrics(poses, summary, 2, scale)
        sigs = (self.ctx.parts_sig, self.ctx.constraint_sig, 2, self.ctx.spec_sig)
        ch = res.get("algorithm") or {}
        algo = {"id": ch.get("id", "hybrid_box"), "label": ch.get("label", ALGORITHMS["hybrid_box"]),
                "reason": f"{ch.get('reason', '')}; brackets bridge up to {res['bracket_reach_mm']:.0f} mm and the "
                          f"hardware cost is weighted by the cost slider", "search": "brkga+lahc", "decoder": "box",
                "detail": "Manufacturable Design: BRKGA + LAHC on the Stage 2 box decoder with mount synthesis"}
        e = LayoutEntry(id=lid, hash=layout_hash(2, poses), stage=2, mode="manufacturable", algorithm=algo,
                        status="VALIDATED" if summary["valid"] else "REJECTED", parts_sig=sigs[0],
                        constraint_sig=sigs[1], poses=poses, geo=geo,
                        validation={"certified": summary["valid"], "validator_version": "1.0", "tolerance_mm": 0.001,
                                    "pairs": summary["pairs"], "statics": summary["statics"], "levels": summary["levels"],
                                    "min_clearance_mm": summary["min_clearance_mm"], "checked_at": now_iso(),
                                    "violations": summary["violations"], "engineering_violations": res["violations"],
                                    "relaxed_rules": res["validation"]["relaxed_rules"],
                                    "brackets": res["validation"]["brackets"]},
                        keys=None, spec_sig="mfg:" + sigs[3], meta=jsonable(meta), origin="search", part_scale=scale)
        self._compute_physics(e)
        e.revs = {k: self.store.revs[k] for k in ("parts_rev", "constraint_rev", "mass_rev", "weights_rev")}
        self._score_entry(e)
        self.archive[e.id] = e
        self._persist(e)
        res["layout_id"] = lid
        res["algorithm"] = {"id": algo["id"], "label": algo["label"], "reason": algo["reason"]}
        # the final verdict is the archived layout's: COM box with the bracket masses included, all violations
        res["feasible"] = e.status == "VALIDATED"
        res["violations"] = list(e.metrics.get("violations", []))
        res["verdict"] = None if res["feasible"] else "NO FEASIBLE LAYOUT FOUND (not proven infeasible)"
        res["layout_status"] = e.status
        res["com_mm"] = e.metrics.get("com_mm")
        for it, x in zip(res["items"], items):
            it["item_id"] = x["id"]
        res["exports"] = [{**x, "url": f"/api/mfg/download/{x['url']}"} for x in res["exports"]]
        (out / "mfg.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
        self.broadcast("study.update", {"study": "mfg", "progress": 1.0, "partial": {"status": "DONE", "layout_id": lid}})

    def mfg(self) -> dict | None:
        if self.ctx is None:
            return None
        p = self._mfg_dir() / "mfg.json"
        L = self.ladders.get("__mfg__")
        if L is not None and L.get("error"):
            return {"status": "ERROR", "detail": L["error"]}
        if L is not None and not L.get("finalised"):
            return {"status": "RUNNING"}
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def mfg_file(self, name: str) -> Path:
        p = (self._mfg_dir() / name).resolve()
        if self._mfg_dir().resolve() not in p.parents or not p.is_file() or p.suffix not in (".stl", ".csv"):
            raise KeyError(name)
        return p

    # =========================================================================================== free rotation
    def _free_rotation_path(self) -> Path:
        return self.store.cache / f"free_rotation_{self.ctx.parts_sig if self.ctx else 'none'}.json"

    def start_free_rotation(self, opts: dict | None = None) -> dict:
        """Research experiment: arbitrary rotations from the shortest validated Stage 1 layout of these parts."""
        import pickle
        from ..experiments.free_rotation import free_rotation_job
        if self.ctx is None:
            raise ValueError("no packable parts")
        L = self.ladders.get("__free_rotation__")
        if L is not None and not L["future"].done():
            raise ValueError("the free-rotation experiment is already running")
        pids = set(self.ctx.records)
        start = None                                 # the shortest, read one at a time (most are not in memory)
        for lid in self.archive.ids_of(1, self.ctx.parts_sig):
            e = self.archive.load(lid, keep=False) if self.archive.status_of(lid) in ("VALIDATED", "FINAL") else None
            if e is not None and {p for p, _, _ in e.poses} == pids and (
                    start is None or e.geo.get("length_used_mm", math.inf) < start.geo.get("length_used_mm", math.inf)):
                start = e
        if start is None:
            raise ValueError("no validated Stage 1 layout of the current parts yet")
        snap = self.store.cache / f"freerot_records_{self.ctx.parts_sig}.pkl"
        snap.write_bytes(pickle.dumps(self._active_records(), protocol=pickle.HIGHEST_PROTOCOL))
        path = self._free_rotation_path()
        path.unlink(missing_ok=True)
        budget = float((opts or {}).get("budget_s", 120.0))
        poses = [(p, int(o), np.asarray(t, float)) for p, o, t in start.poses]
        fut = self.ladder_pool.submit(formfactor.call_with, formfactor.current(), free_rotation_job, str(snap), poses, start.id, str(path), budget,
                                      int((opts or {}).get("seed", 20261022)))
        self.ladders["__free_rotation__"] = {"future": fut, "path": path, "mtime": None, "status": "PENDING",
                                             "progress": 0.0, "study": "free_rotation"}
        return {"status": "RUNNING", "start_layout_id": start.id, "budget_s": budget}

    def free_rotation(self) -> dict | None:
        if self.ctx is None:
            return None
        L = self.ladders.get("__free_rotation__")
        if L is not None and L["future"].done() and L["future"].exception() is not None:
            return {"status": "ERROR", "detail": repr(L["future"].exception())}
        p = self._free_rotation_path()
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                d = {"status": "RUNNING"}
            if d.get("status") == "RUNNING" and not (L is not None and not L["future"].done()):
                d["status"] = "STOPPED"
            return d
        if L is not None and not L["future"].done():
            return {"status": "RUNNING"}
        return None

    # =========================================================================================== V2 brackets
    CONTEST_RESULTS = Path(__file__).resolve().parents[4] / "data" / "gd_contest" / "results.json"

    def gd_contest(self) -> dict | None:
        """Generative-design contest results (run offline with scripts/gd_contest.py; shipped with the app)."""
        try:
            return json.loads(self.CONTEST_RESULTS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    # what a user may set for one bracket (Mounting Hardware tab): material used, as the volume fraction of its
    # reserved box, and the minimum member thickness (mm); "auto" lets the design run choose
    BRACKET_VOL_FRAC = (0.02, 0.8)
    BRACKET_MEMBER_MM = (1.0, 12.0)

    @staticmethod
    def _check_design_settings(new: dict) -> dict:
        """The bracket design settings in a settings change, checked before anything changes: the launch environment
        (a gd.environment preset id) and the default AM material (gd.materials). InvalidSetting when unknown."""
        from ..gd import environment as envs
        from ..gd import materials as mats
        out = {}
        try:
            if new.get("launch_environment") is not None:
                out["launch_environment"] = envs.get(str(new["launch_environment"])).id
            if new.get("bracket_material") is not None:
                out["bracket_material"] = mats.for_kind("metal_am", str(new["bracket_material"]))
        except (KeyError, ValueError) as exc:
            raise InvalidSetting(exc.args[0]) from exc
        return out

    def _design_defaults(self) -> tuple[str, str]:
        """(launch environment, AM material) the brackets are designed for now: the project settings, or the
        defaults when a project file holds an id that no longer exists."""
        from ..gd import environment as envs
        from ..gd import materials as mats
        s = self.store.settings
        try:
            env_id = envs.get(s.get("launch_environment")).id
        except KeyError:
            env_id = envs.DEFAULT
        try:
            mat_id = mats.for_kind("metal_am", s.get("bracket_material"))
        except (KeyError, ValueError):
            mat_id = mats.DEFAULT_AM
        return env_id, mat_id

    @classmethod
    def _bracket_override(cls, b: dict, ov: dict) -> dict:
        """One bracket's design settings from a request, checked: `material` (an AM material, metal-AM brackets
        only; None or "default": the project's), `vol_frac` and `min_member_mm` (a number in range, or None /
        "auto"). Only the keys given are returned. InvalidSetting when one is out of range or unknown."""
        from ..gd import materials as mats
        if not isinstance(ov, dict):
            raise InvalidSetting(f"{b['pid']}: the settings of a bracket are an object")
        bad = set(ov) - {"material", "vol_frac", "min_member_mm"}
        if bad:
            raise InvalidSetting(f"{b['pid']}: unknown bracket setting(s) {', '.join(sorted(bad))}")
        out = {}
        if "material" in ov:
            m = ov["material"]
            if m in (None, "default", "auto"):
                out["material"] = None
            elif b["kind"] != "metal_am":
                raise InvalidSetting(f"{b['pid']}: cradles and clamp bands are machined {mats.MACHINED}")
            else:
                try:
                    out["material"] = mats.for_kind("metal_am", str(m))
                except (KeyError, ValueError) as exc:
                    raise InvalidSetting(exc.args[0]) from exc
        for k, (lo, hi), what in (("vol_frac", cls.BRACKET_VOL_FRAC, "material used"),
                                  ("min_member_mm", cls.BRACKET_MEMBER_MM, "minimum member thickness")):
            if k not in ov:
                continue
            v = ov[k]
            if v in (None, "auto"):
                out[k] = "auto"
                continue
            try:
                x = float(v)
            except (TypeError, ValueError) as exc:
                raise InvalidSetting(f"{b['pid']}: {what} must be a number or \"auto\"") from exc
            if not (math.isfinite(x) and lo <= x <= hi):
                raise InvalidSetting(f"{b['pid']}: {what} {x:g} is outside {lo:g} … {hi:g}")
            out[k] = x
        return out

    def design_options(self) -> dict:
        """What the bracket designs can be set to (Mounting Hardware tab): the launch environments, the materials
        (AM for metal-AM brackets; cradles and clamps are machined), the ranges of the per-bracket settings with the
        automatic run's ladder and the AM minimum wall, and the project's current environment and material."""
        from ..gd import environment as envs
        from ..gd import materials as mats
        from ..gd.contest import VOL_LADDER
        from ..gd.design import AM_MIN_WALL_MM, MEMBER_KWARG, winner_key
        env_id, mat_id = self._design_defaults()
        key = winner_key(str(self.CONTEST_RESULTS))
        return {"environments": [e.summary() for e in envs.ENVIRONMENTS.values()],
                "materials": [{k: m[k] for k in ("id", "name", "process", "E_mpa", "yield_mpa", "ultimate_mpa",
                                                 "source")} | {"density_g_cm3": m["rho_t_mm3"] * 1e9}
                              for m in mats.MATERIALS.values()],
                "allowables": mats.ALLOWABLES, "machined": mats.MACHINED,
                "vol_frac": {"range": list(self.BRACKET_VOL_FRAC), "ladder": list(VOL_LADDER)},
                "min_member_mm": {"range": list(self.BRACKET_MEMBER_MM), "am_min_wall_mm": AM_MIN_WALL_MM,
                                  "generator_sets_member_size": key in MEMBER_KWARG},
                "generator": key, "launch_environment": env_id, "bracket_material": mat_id}

    def _bracket_outdated(self, e: LayoutEntry, b: dict, d: dict) -> bool:
        """A design made for another launch environment, or in another AM material than the bracket's own setting
        or the project default (designs from before the launch environments count as another environment)."""
        env_id, mat_id = self._design_defaults()
        if d.get("environment") != env_id:
            return True
        if b["kind"] == "metal_am":
            want = (((e.meta or {}).get("bracket_overrides") or {}).get(b["pid"]) or {}).get("material") or mat_id
            return d.get("material") != want
        return False

    def start_bracket_design(self, layout_id: str, pids: list | None = None, overrides: dict | None = None) -> dict:
        """Design every metal-AM, cradle and tube-clamp bracket of a Stage 2 layout inside its reserved box (contest
        winner for metal AM, rule-based cradles and clamp bands), each checked with CalculiX and NGSolve under the
        project's launch environment; the designed solids replace the estimates and envelopes in the layout's 3D
        views, physics, exports and fit proof.

        `pids`: design only these brackets ("Redesign" in the Mounting Hardware tab); the others keep their designs.
        `overrides`: {pid: {material, vol_frac, min_member_mm}}, the user's settings for a bracket (_bracket_override),
        kept with the layout (meta bracket_overrides) for later runs; a metal-AM bracket without a material of its own
        gets the project's bracket_material."""
        import pickle
        from ..gd.design import DESIGNED_KINDS, design_job
        e = self.archive.get(layout_id)
        if e is None:
            raise KeyError(layout_id)
        brs = (e.meta or {}).get("brackets") or []
        designable = {b["pid"]: b for b in brs if b["kind"] in DESIGNED_KINDS}
        if e.stage != 2 or not designable:
            raise ValueError("this layout has no metal-AM, cradle or clamp bracket to design")
        if not isinstance(pids or [], list) or not isinstance(overrides or {}, dict):
            raise InvalidSetting("pids is a list of part ids, overrides an object {part id: settings}")
        only = list(dict.fromkeys(pids or []))
        unknown = [str(p) for p in [*only, *(overrides or {})] if p not in designable]
        if unknown:
            raise InvalidSetting(f"{e.id} has no designed bracket for {', '.join(dict.fromkeys(unknown))}")
        cleaned = {p: self._bracket_override(designable[p], ov) for p, ov in (overrides or {}).items()}
        L = self.ladders.get("__bracket_design__")
        if L is not None and not L.get("finalised"):
            raise ValueError("a bracket design run is already in progress")
        stored = dict((e.meta or {}).get("bracket_overrides") or {})
        for p, ov in cleaned.items():
            stored[p] = {**(stored.get(p) or {}), **ov}
        if cleaned:
            e.meta = jsonable({**(e.meta or {}), "bracket_overrides": stored})
            self._persist(e)
        env_id, mat_id = self._design_defaults()
        materials = {p: (stored.get(p) or {}).get("material") or mat_id
                     for p, b in designable.items() if b["kind"] == "metal_am"}
        recs = self.layout_records(e)
        phys = self._phys(e.part_scale)
        pad_o = (e.meta or {}).get("pad_orients", {})
        poses = {pid: (int(pad_o.get(pid, o)), np.asarray(t, float)) for pid, o, t in e.poses}
        out = self.store.cache / "items" / e.id
        snap = out / "bracket_design.pkl"
        out.mkdir(parents=True, exist_ok=True)
        snap.write_bytes(pickle.dumps({"layout_id": e.id, "brackets": brs, "records": recs, "poses": poses,
                                       "masses": {p: (x.mass_kg if x is not None else None) for p, x in phys.items()},
                                       "results_path": str(self.CONTEST_RESULTS), "environment": env_id,
                                       "materials": materials, "overrides": stored, "only": only},
                                      protocol=pickle.HIGHEST_PROTOCOL))
        (out / "progress.json").unlink(missing_ok=True)
        fut = self.ladder_pool.submit(formfactor.call_with, formfactor.current(), design_job, str(snap), str(out))
        self.ladders["__bracket_design__"] = {"future": fut, "path": out / "progress.json", "mtime": None,
                                              "status": "PENDING", "progress": 0.0, "study": "bracket_design",
                                              "settings": self._settings_view()}
        self._design_lid = e.id                      # kept in memory until the run has finished (_enforce_memory)
        wf = asyncio.wrap_future(fut, loop=self.loop)
        wf.add_done_callback(lambda f, lid=e.id, o=out: self._on_bracket_design(f, lid, o))
        rows = [{"k": k, "pid": b["pid"], "kind": b["kind"], "status": "queued"}
                for k, b in enumerate(brs) if b["kind"] in DESIGNED_KINDS and (not only or b["pid"] in only)]
        self.broadcast("study.update", {"study": "bracket_design", "progress": 0.0, "partial": self._design_progress(
            {"layout_id": e.id, "brackets": rows, "n_total": len(rows), "n_done": 0, "seconds": 0.0}, "PENDING")})
        return {"status": "RUNNING", "layout_id": e.id, "brackets": len(rows), "environment": env_id}

    @staticmethod
    def _design_progress(res: dict, status: str) -> dict:
        """What the progress bars show of a bracket design run: one row per bracket (queued / running / done, time,
        mass, result), how many are done, the time so far and the estimated time left (gd.design.design_job)."""
        return {"status": status, "layout_id": res.get("layout_id"), "brackets": res.get("brackets") or [],
                "n_total": res.get("n_total"), "n_done": res.get("n_done"), "workers": res.get("workers"),
                "seconds": res.get("seconds"), "eta_s": res.get("eta_s")}

    def _search_settled(self) -> bool:
        """No island job in flight and no validation queued or running: the best layout can no longer change."""
        if self.val_queue or self.val_pending:
            return False
        return not any(w.busy for w in getattr(self, "workers", []) if getattr(w, "role", None) == "island")

    def _maybe_auto_design(self) -> None:
        """V2 (setting auto_design_brackets, on by default): when the search is paused (Pause is its only stop),
        design the brackets of the best Stage 2 layout that are still estimates or catalogue envelopes, so its 3D
        views and exports show the real bracket shapes. It waits until the validations still queued at the pause have finished (the best
        can change until then), runs one design job at a time, and designs each layout once (a bracket already
        designed or tried is not designed again; the button can always start a run)."""
        from ..gd.design import DESIGNED_KINDS
        if not self.store.settings.get("auto_design_brackets", True):
            return
        if self.__dict__.get("_settle_at") is not None:   # a slider is still moving: once it has settled (_tick)
            return
        if not self._search_settled():               # search jobs or validations still running after the pause: the
            self._auto_design_due = True             # best may still change — run when they have finished (_tick)
            return
        if self.best_id is None:
            return
        e = self.archive.get(self.best_id)
        if e is None or e.stage != 2 or e.status not in ("VALIDATED", "FINAL"):
            return
        done = (e.meta or {}).get("bracket_designs") or {}
        todo = [b["pid"] for b in (e.meta or {}).get("brackets") or [] if b["kind"] in DESIGNED_KINDS and
                (b["pid"] not in done or self._bracket_outdated(e, b, done[b["pid"]]))]
        if not todo:
            self._sync_saved_stl(e)                  # designed before: the saved STL files follow it
            return
        L = self.ladders.get("__bracket_design__")
        if L is not None and not L.get("finalised"):
            return
        tried = self.__dict__.setdefault("_auto_design_tried", set())
        key = (e.id, *self._design_defaults())       # once per layout and launch environment / material: a failed
        if key in tried:                             # run is not repeated on its own
            return
        tried.add(key)
        try:
            self.start_bracket_design(e.id, pids=todo)
        except (KeyError, ValueError, OSError) as exc:
            self._error(f"automatic bracket design not started: {exc}")

    @staticmethod
    def _carry_minimum(old: dict | None, new: dict) -> dict:
        """A bracket designed at a set material use finds no FEA minimum of its own: the minimum an earlier automatic
        run found (and that run's ladder) is kept when it had the same material, member thickness and environment."""
        if new.get("min_vol_frac") is not None or not old or old.get("min_vol_frac") is None:
            return new
        o, n = old.get("settings") or {}, new.get("settings") or {}
        if old.get("environment") != new.get("environment") or o.get("material") != n.get("material") or \
                o.get("min_member_mm") != n.get("min_member_mm"):
            return new
        return {**new, "min_vol_frac": old["min_vol_frac"], "min_vol_frac_carried": True,
                "auto_ladder": old.get("auto_ladder") or old.get("ladder")}

    def _on_bracket_design(self, fut, lid: str, out: Path) -> None:
        L = self.ladders.get("__bracket_design__")
        try:
            if fut.cancelled():
                return
            if fut.exception() is not None:
                self._error(f"bracket design failed: {fut.exception()!r}")
                return
            res = json.loads((out / "progress.json").read_text(encoding="utf-8"))
            e = self.archive.get(lid)
            if e is None:
                return
            meta = dict(e.meta or {})
            old = meta.get("bracket_designs") or {}       # a run of some brackets: the others keep their designs
            meta["bracket_designs"] = {**old, **{p: self._carry_minimum(old.get(p), d)
                                                 for p, d in (res.get("designs") or {}).items()}}
            e.meta = jsonable(meta)
            self._compute_physics(e)                  # designed masses replace the estimates
            self._score_entry(e)
            self._persist(e)
            for k in [k for k in self.proof_cache if k[0] == lid]:
                self.proof_cache.pop(k, None)
            # clients showing this layout (the Overview's best, a least-violating candidate) get it again, with the
            # designed solids' mesh URLs and masses — they keep a copy and would otherwise draw the boxes
            self.broadcast("layout.updated", {"layout": self.layout_json(e), "reason": "brackets designed"})
            self.broadcast("study.update", {"study": "bracket_design", "progress": 1.0,
                                            "partial": self._design_progress(res, "DONE")})
            # the designed assembly as STL files — unless a slider moved during the run and this layout is no longer
            # the best: its brackets would belong to the old settings (the next pause saves the new best)
            if lid == self.best_id or (L is not None and L.get("settings") == self._settings_view()):
                self._save_stl(e, "bracket design run finished")
        except Exception as exc:  # noqa: BLE001
            self._error(f"bracket designs could not be applied: {exc!r}")
        finally:
            if L is not None:
                L["finalised"] = True
            self._design_lid = None
        if self.run_status == "PAUSED":                       # the best may have changed while this one ran
            self._maybe_auto_design()

    # =========================================================================================== saved STL files (V2)
    def _saved_stl_dir(self) -> Path:
        from ..report.saved_stl import FOLDER
        return self.store.folder / FOLDER

    def saved_stl(self) -> dict:
        """The saved STL files (report/saved_stl.py): their manifest, the folder, and the layout being saved now."""
        from ..report.saved_stl import read_manifest
        m = read_manifest(self._saved_stl_dir()) or {"status": "none"}
        m["folder"] = str(self._saved_stl_dir())
        m["saving"] = self.__dict__.get("_stl_pending")
        return m

    def saved_stl_zip(self) -> bytes:
        """The saved set as one zip, read on the saved-STL thread (never half-written)."""
        from ..report.saved_stl import read_manifest, zip_set
        folder = self._saved_stl_dir()
        if read_manifest(folder) is None:
            raise KeyError("no saved STL files yet")
        ex = self.__dict__.get("_stl_io")
        return ex.submit(zip_set, folder).result() if ex is not None else zip_set(folder)

    def save_stl(self, layout_id: str) -> dict:
        """Save a Stage 2 layout's STL files now (Mounting Hardware tab); written in the background."""
        e = self.archive.get(layout_id)
        if e is None:
            raise KeyError(layout_id)
        if e.stage != 2:
            raise ValueError("only a Stage 2 layout has brackets to save")
        self._save_stl(e, "saved from the Mounting Hardware tab")
        return {"status": "SAVING", "layout_id": e.id, "folder": str(self._saved_stl_dir())}

    def _settings_view(self) -> dict:
        """The settings a search result depends on: sliders, part size, CubeSat size, stage, COM target and the
        compactness definition (not display options, the automatic design switch or the speed/quality slider, which
        changes nothing since the search runs until Pause: NOT_SEARCH_SLIDERS)."""
        s = self.store.settings
        v = {k: s.get(k) for k in ("form_factor", "stage", "part_scale_pct", "target_com_mm", "compactness_definition")}
        v["sliders"] = {k: x for k, x in (s.get("sliders") or {}).items() if k not in NOT_SEARCH_SLIDERS}
        return json.loads(json.dumps(v))

    def _stl_items(self, e: LayoutEntry) -> tuple[list, list, list]:
        """Binary STL (world mm) of every placed part and of every bracket with a real solid — built (direct mount,
        machined block, sheet bracket, standoff) or designed; a bracket still drawn as its reserved box or catalogue
        envelope is left out and listed."""
        from ..geometry.stl_io import stl_bytes
        from ..report.build import _hardware_meshes, _placed_parts, _safe
        names, parts = {}, []
        for pid, r, o, t in _placed_parts(self, e):
            names[pid] = r.name
            parts.append((f"{_safe(pid)}_{_safe(r.name)}", stl_bytes(to_world(r.v, o, t), r.f, f"t2s {e.id} {r.name} "
                                                                     "world mm"), {"part_id": pid, "part": r.name}))
        designs = (e.meta or {}).get("bracket_designs") or {}
        brackets, left_out = [], []
        for it, _, v, f in _hardware_meshes(self, e):
            pid = it.get("for_part")
            kind = it.get("bracket_kind") or it.get("kind")
            desc = {"part_id": pid, "part": names.get(pid, pid), "kind": kind, "process": it.get("process"),
                    "item": it["id"], "mass_kg": it.get("mass_kg"), "designed": bool(it.get("designed"))}
            if it.get("kind") == "bracket" and not it.get("designed") and not it.get("exact"):
                d = designs.get(pid)
                why = (f"design failed: {d.get('reason') or 'no solid'}" if d else "not designed yet") + \
                    (" (catalogue envelope)" if kind == "clamp" else " (reserved box)")
                left_out.append({**desc, "why": why})
                continue
            if it.get("designed") and designs.get(pid):
                desc.update(passed=bool(designs[pid].get("passed")), generator=designs[pid].get("generator"))
            stem = f"{'AM' if it.get('process') == 'metal_am' else _safe(str(kind))}_{_safe(names.get(pid, str(pid)))}"
            brackets.append((f"{stem}_{it['id'].rsplit('-', 1)[-1]}", stl_bytes(v, f, f"t2s {e.id} {it['id']} {kind}"),
                             desc))
        return parts, brackets, left_out

    def _save_stl(self, e: LayoutEntry, why: str) -> None:
        """Write the saved STL set for this layout (in the background, after any file work asked for before)."""
        from ..report.saved_stl import write_set
        folder = self._saved_stl_dir()
        info = {"settings": self._settings_view(), "why": why, "stage": e.stage, "part_scale": e.part_scale,
                "layout_status": e.status}

        def job():
            parts, brackets, left_out = self._stl_items(e)
            return write_set(folder, e.id, parts, brackets, {**info, "left_out": left_out})
        self._stl_pending = e.id
        self._stl_submit(job, f"saving the STL files of {e.id}")

    def _sync_saved_stl(self, e: LayoutEntry) -> None:
        """The saved STL files follow the best layout once its brackets are designed: written again unless they hold
        this layout with its brackets at the current settings already, or a save of it is under way."""
        from ..report.saved_stl import read_manifest
        if self.__dict__.get("_stl_pending") == e.id:
            return
        m = read_manifest(self._saved_stl_dir())
        if m and m.get("layout_id") == e.id and m.get("status") == "complete" and \
                m.get("settings") == self._settings_view():
            return
        self._save_stl(e, "the search stopped on this layout; its brackets were designed before")

    def _drop_saved_brackets(self, reason: str) -> None:
        """A slider (or another search setting) moved: the saved bracket files belong to the layout found at the old
        settings — delete them and write the assembly again without them."""
        from ..report.saved_stl import remove_brackets
        folder = self._saved_stl_dir()
        self._stl_submit(lambda: remove_brackets(folder, reason), "removing the saved bracket STL files")

    def _stl_submit(self, fn, what: str) -> None:
        """Saved-STL file work runs on one background thread, in the order it was asked for; the clients hear when
        something changed (saved_stl.updated)."""
        from concurrent.futures import Future, ThreadPoolExecutor
        self._stl_queued = self.__dict__.get("_stl_queued", 0) + 1
        loop = self.__dict__.get("loop")
        if loop is None:                             # no event loop (tests): do it here
            fut: Future = Future()
            try:
                fut.set_result(fn())
            except Exception as exc:  # noqa: BLE001 - reported by _on_stl_done
                fut.set_exception(exc)
            self._on_stl_done(fut, what)
            return
        ex = self.__dict__.get("_stl_io")
        if ex is None:
            ex = self._stl_io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saved-stl")
        ex.submit(fn).add_done_callback(lambda f: loop.call_soon_threadsafe(self._on_stl_done, f, what))

    def _on_stl_done(self, fut, what: str) -> None:
        self._stl_queued = max(0, self.__dict__.get("_stl_queued", 1) - 1)
        if not self._stl_queued:
            self._stl_pending = None
        exc = fut.exception()
        if exc is not None:
            self._error(f"{what} failed: {exc!r} (is a file in {self._saved_stl_dir()} open in another program?)")
            return
        if fut.result() is not None:                 # None: nothing changed (no saved brackets to remove)
            self.broadcast("saved_stl.updated", {"saved_stl": self.saved_stl()})

    # =========================================================================================== largest size (V2)
    def _largest_size_path(self) -> Path:
        full = parts_signature({pid: self.records[pid] for pid in self._active_records()})
        return self.store.cache / (f"largest_size_{full}_{self._stage2_mode()}_am{self._am_level()}_"
                                   f"{formfactor.current()}.json")

    def start_largest_size(self, opts: dict | None = None) -> dict:
        """Bisection on the part-size factor: the largest size at which a fixed-effort Stage 2 search finds a
        certified layout (search-based)."""
        import pickle
        from ..bench.largest_size import largest_size_job
        if self.ctx is None:
            raise ValueError("no packable parts")
        L = self.ladders.get("__largest_size__")
        if L is not None and not L["future"].done():
            raise ValueError("a largest-size search is already running")
        recs = {pid: self.rec_at(pid, 1.0) for pid in self._active_records()}       # full size
        snap = self.store.cache / "largest_size_records.pkl"
        snap.write_bytes(pickle.dumps(recs, protocol=pickle.HIGHEST_PROTOCOL))
        path = self._largest_size_path()
        path.unlink(missing_ok=True)
        fut = self.ladder_pool.submit(formfactor.call_with, formfactor.current(), largest_size_job, str(snap),
                                      self._stage2_mode(), dict(self.store.settings["sliders"]), str(path),
                                      self._am_level(), dict(opts or {}))
        self.ladders["__largest_size__"] = {"future": fut, "path": path, "mtime": None, "status": "PENDING",
                                            "progress": 0.0, "study": "largest_size"}
        return {"status": "PENDING"}

    def largest_size(self) -> dict | None:
        if self.ctx is None:
            return None
        p = self._largest_size_path()
        L = self.ladders.get("__largest_size__")
        if L is not None and L["future"].done() and L["future"].exception() is not None:
            return {"status": "ERROR", "detail": repr(L["future"].exception())}
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"status": "RUNNING", "rows": []}
        if L is not None and not L["future"].done():
            return {"status": "PENDING", "rows": []}
        return None

    # =========================================================================================== attribution
    def _attribution_path(self) -> Path:
        return self.store.cache / f"attribution_{self.ctx.parts_sig}_{self._stage2_mode()}.json"

    def start_attribution(self, opts: dict | None = None) -> dict:
        import pickle
        from ..constraints.attribution import attribution_job
        if self.ctx is None:
            raise ValueError("no packable parts")
        recs = {pid: self.rec_at(pid, self._ctx_scale()) for pid in self._active_records()}   # at the part size
        snap = self.store.cache / f"attr_records_{self.ctx.parts_sig}.pkl"
        snap.write_bytes(pickle.dumps(recs, protocol=pickle.HIGHEST_PROTOCOL))
        path = self._attribution_path()
        path.unlink(missing_ok=True)
        fut = self.ladder_pool.submit(formfactor.call_with, formfactor.current(), attribution_job, str(snap), self._stage2_mode(),
                                      dict(self.store.settings["sliders"]), str(path), dict(opts or self.attribution_opts))
        self.ladders["__attribution__"] = {"future": fut, "path": path, "mtime": None, "status": "PENDING",
                                           "progress": 0.0, "study": "attribution"}
        return {"status": "PENDING", "mode": self._stage2_mode()}

    def attribution(self) -> dict | None:
        if self.ctx is None:
            return None
        p = self._attribution_path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        L = self.ladders.get("__attribution__")
        if L is not None and not L["future"].done():
            return {"status": "PENDING", "rows": []}
        return None

    def fidelity_summary(self) -> dict:
        out = []
        for pid, e in self.store.entries.items():
            f = self.fidelity(pid)
            out.append({"part_id": pid, "name": e.name, "status": f["status"] if f else "NOT_RUN",
                        "chosen": f.get("chosen", {}) if f else {},
                        "in_use": self.ctx.levels.get(pid) if self.ctx is not None else None})
        return {"parts": out}

    def remove_part(self, pid: str) -> None:
        e = self.store.entries.get(pid)
        if e is None:
            raise KeyError(pid)
        self.store.remove(pid)
        self.records.pop(pid, None)
        self.geoms.pop(pid, None)
        self.quick.pop(pid, None)
        self._refresh_inputs(f"removed {e.name}")

    def run_control(self, action: str) -> None:
        if action in ("start", "resume"):
            self.search_requested = True
            if self.ctx is None:
                pending = self._confirmed_builds_pending()
                self._set_status("IDLE", f"analysing {pending} part(s)…" if pending else "no packable parts")
                return
            self._set_status("SEARCHING", "started" if action == "start" else "resumed")
        elif action == "pause":
            self.search_requested = False
            self._set_status("PAUSED", "paused by the user")
        elif action == "rerun":
            self.ctx_counter += 1
            if self.ctx is not None:
                for w in self.workers:
                    self._send_context(w)
                self._clock_restart()
                self._set_status("SEARCHING", "re-run with new random seeds")
        elif action == "reset":
            self.archive.rewrite(keep=lambda lid, status: status == "FINAL")
            self.by_hash = self.archive.hashes()
            self._table, self._dfront = None, None
            self._tables.clear()
            self._fam_ver.clear()
            if self.ctx is not None:
                self.norms[self.ctx.ctx_id] = Normaliser()
                self.raw_pool[self.ctx.ctx_id] = []
            self.store.counters["epoch"] += 1
            self.store.save()
            self.best_id = None
            self._select_best()
            self.run_control("rerun")
            for c in list(self.clients):
                self.send(c, "state.snapshot", self.snapshot())
        else:
            raise ValueError(f"unknown action {action!r}")

    # =========================================================================================== proofs
    def _files_for(self, poses) -> dict:
        out = {}
        for pid, _, _ in poses:
            e = self.store.entries.get(pid)
            out[pid] = (e.file if e else self.records[pid].file, self.records[pid].sha256)
        return out

    def build_proof(self, layout_id: str) -> dict:
        """Full re-validation with plane certificates + certificate JSON + proof text (runs in a thread)."""
        from ..collision.validate import StageSpec
        from ..proof.certificate import build_certificate, proof_markdown
        e = self.archive[layout_id]
        key = (layout_id, e.revs.get("mass_rev"))
        if key in self.proof_cache:
            return self.proof_cache[key]
        if not self._current(e) and any(pid not in self.records for pid, _, _ in e.poses):
            raise ValueError("this layout's parts are no longer in the project")
        records = self.layout_records(e)                  # at the part size the layout was found at
        if e.stage == 2:
            from ..constraints.stage2_model import Stage2Model
            model = Stage2Model(records, (e.meta or {}).get("mode", "default"))
            spec = model.spec(e.meta or {}, relaxed=bool(e.validation.get("relaxed_rules")))
        else:
            spec = StageSpec(1, ENCLOSURE_LO.copy(), ENCLOSURE_HI.copy(), 0.0, 0.0)
        geoms = self.layout_geoms(e)
        rep = Validator(geoms).validate(e.poses, spec, want_planes=True)
        cert = build_certificate(e.id, rep, records, e.poses, spec, self._files_for(e.poses),
                                 extra={"layout_hash": e.hash, "app_version": VERSION, "part_scale": e.part_scale},
                                 brackets=self._bracket_cert(e))
        from ..optimise.bounds import lower_bounds
        lbs = lower_bounds(list(records.values()))
        metrics = dict(e.metrics)
        metrics["lower_bounds"] = [(f"{b['name']} (valid for {b['valid_for']})", b["value_mm"], b["why"])
                                   for b in lbs if b.get("value_mm") is not None]
        cps = self.cpsat_results.get(e.parts_sig) or {}
        if e.stage == 1 and cps.get("lower_bound_mm") is not None:
            metrics["lower_bounds"].append(
                ("CP-SAT best bound (valid for single-box proxies only)", cps["lower_bound_mm"],
                 f"OR-Tools CP-SAT, {cps.get('status')}, {cps.get('seconds', 0):.0f} s, 0.1 mm grid with dimensions "
                 "rounded up; not a bound for the true shapes"))
        md = proof_markdown(cert, rep, metrics)
        out = {"markdown": md, "certificate": cert, "valid": rep.valid}
        self.proof_cache[key] = out
        for k in list(self.proof_cache)[:-32]:          # an open proof view asks again at every new best: bounded
            self.proof_cache.pop(k, None)
        return out

    def _bracket_cert(self, e: LayoutEntry) -> list[dict]:
        """V2 Stage 2 brackets for the certificate: reserved box and every vertex of the solid in it (the designed
        solid when there is one; a cradle or metal-AM bracket not designed yet has only its box)."""
        from ..mfg.brackets import cert_entry
        out = []
        for b in (e.meta or {}).get("brackets") or []:
            d = (e.meta.get("bracket_designs") or {}).get(b["pid"])
            verts = None
            if d and d.get("vertices_file"):
                p = self.store.cache / "items" / e.id / d["vertices_file"]
                if p.is_file():
                    verts = np.load(p)
            out.append(cert_entry(b, verts))
        return out

    def finalize(self, layout_id: str) -> dict:
        e = self.archive[layout_id]
        if not self._current(e):
            raise ValueError("only a layout validated for the current inputs can be frozen as FINAL")
        p = self.build_proof(layout_id)
        if not p["valid"]:
            raise ValueError("full re-validation failed; the layout was not frozen")
        e.status = "FINAL"
        e.validation["final_checked_at"] = now_iso()
        self._persist(e, row=False)       # appended: its last line wins (its objective row stays the same, "ok")
        return self.layout_json(e)

    # =========================================================================================== meshes
    def mesh_bytes(self, pid: str) -> bytes:
        rec = self.records.get(pid)
        e = self.store.entries.get(pid)
        if rec is not None and e is not None and rec.units == e.units:
            v, f = rec.v, rec.f
        elif e is not None:
            tri, _ = read_stl_bytes(self.store.stl_path(e).read_bytes())
            tri = tri * UNIT_TO_MM.get(e.units or "mm", 1.0)
            pts = tri.reshape(-1, 3)
            c = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
            v = pts - c
            f = np.arange(len(pts)).reshape(-1, 3)
        else:
            raise KeyError(pid)
        v32 = np.ascontiguousarray(v, dtype="<f4")
        f32 = np.ascontiguousarray(f, dtype="<u4")
        head = np.array([len(v32), len(f32)], dtype="<u4")
        return head.tobytes() + v32.tobytes() + f32.tobytes()
