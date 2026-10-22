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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..collision.geom import part_geom_from_record, to_world
from ..collision.validate import Validator
from ..constraints import stage2 as s2
from ..core.rotations import ROTATIONS_F, as_lists
from ..geometry.stl_io import UNIT_TO_MM, read_stl_bytes
from ..objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO
from ..optimise.brkga import Evaluator
from ..optimise.scalarize import Normaliser, alpha_from, dominates, scalarise, slider_weights
from ..optimise.selector import ALGORITHMS, AlgorithmChoice, grid_map, part_stats, select_algorithm, sweep
from ..physics.assembly import PartPhys, assembly, com_box_check, inertia_metrics
from .context import SearchContext, build_context, packable, stage2_config, write_context
from .project import PartEntry, ProjectStore, build_record_file, now_iso, part_json, quick_inspect

VERSION = "0.6.0"
ALGORITHM = {"id": "hybrid_box", "label": "Hybrid BRKGA + box decoder", "reason": "archived layout"}
SEARCH_LABELS = {"brkga": "BRKGA + memetic local search", "lahc": "late-acceptance hill climbing",
                 "nsga2": "NSGA-II (pymoo)"}
DECODER_LABELS = {"box": "box decoder", "heightmap": "height-map decoder"}
SELECTOR_SETTLE_S = 1.0


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
MAX_SEARCH_S = 6 * 3600.0


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
        self.archive: dict[str, LayoutEntry] = {}
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
        self.search_t0: float | None = None
        self.last_improve = time.monotonic()
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
        self.selector_log: list[dict] = []
        self._stats = None
        self._stats_sig = None
        self.ladder_pool: ProcessPoolExecutor | None = None
        self.ladders: dict[str, dict] = {}         # part_id -> {future, path, mtime, status}
        self.reps: dict[str, dict] = {}            # part_id -> {algorithm: Representation} (chosen levels)
        self.last_ladder_poll = 0.0
        self.auto_ladder = True
        self.ladder_opts: dict = {}

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
        for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
            os.environ[var] = "1"
        spawn = mp.get_context("spawn")
        self.build_pool = ProcessPoolExecutor(max_workers=2, mp_context=spawn)
        self.ladder_pool = ProcessPoolExecutor(max_workers=1, mp_context=spawn)
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
        if self.ladder_pool:
            procs = list((getattr(self.ladder_pool, "_processes", None) or {}).values())
            self.ladder_pool.shutdown(wait=False, cancel_futures=True)
            for p in procs:                     # a ladder can run for minutes: do not wait for it
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
        if self.ladders and now - self.last_ladder_poll > 1.0:
            self.last_ladder_poll = now
            self._poll_ladders()
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
            stall = 15.0 + 6.0 * float(self.store.settings["sliders"].get("speed_quality", 50))
            if self.best_id is not None and now - self.last_improve > stall:
                self._set_status("CONVERGED", f"no improvement for {stall:.0f} s (speed/quality slider)")
            elif self.search_t0 is not None and now - self.search_t0 > MAX_SEARCH_S:
                self._set_status("CONVERGED", "6 h time limit reached")
        elif self.val_queue or self.val_pending:
            self._dispatch_validation()

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

    def _phys(self) -> dict:
        out = {}
        for pid, rec in self._active_records().items():
            if rec.com_can_mm is None or rec.mass_kg is None:
                out[pid] = None
            else:
                out[pid] = PartPhys(float(rec.mass_kg), np.asarray(rec.com_can_mm, float), rec.inertia_com_kgm2())
        return out

    def _phys_wire(self) -> dict:
        return {pid: None if p is None else (p.mass_kg, p.com_can_mm.tolist(), p.inertia_com_kgm2.tolist())
                for pid, p in self._phys().items()}

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
        ctx = build_context(recs, stage, {pid: self.reps[pid] for pid in recs if pid in self.reps})
        if old is None or ctx.ctx_id != old.ctx_id:
            if old is not None and (ctx.constraint_sig != old.constraint_sig or ctx.stage != old.stage) \
                    and ctx.parts_sig == old.parts_sig:
                self._bump("constraint_rev")
            self.ctx = ctx
            self.ctx_counter += 1
            self.ctx_path = write_context(ctx, self.store.cache / "contexts")
            self.norms.setdefault(ctx.ctx_id, Normaliser())
            self.raw_pool.setdefault(ctx.ctx_id, [])
            self.val_queue = []
            warm = []
            best = self.archive.get(self.best_id) if self.best_id else None
            if best is not None:
                warm.append(best.poses)
            self._apply_choice(self._compute_choice(), restart=False)
            for w in self.workers:
                self._send_context(w, warm)
            self.last_improve = time.monotonic()
            self.search_t0 = time.monotonic()
            if self.run_status in ("CONVERGED", "IDLE") and (self.auto_start or self.search_requested):
                self._set_status("SEARCHING", f"inputs changed: {reason}")
        self.ev = Evaluator(None, ctx.ids, self._phys(), ctx.orient_bounds, ctx.z0, target=self._target(),
                            com_box=ctx.com_box)
        self._restamp_and_rescore(physics=True)
        self.broadcast("project.changed", {"reason": reason})
        self._publish_best("archive", force=True)

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

    def _compute_choice(self) -> AlgorithmChoice:
        s = self.store.settings
        return select_algorithm(int(s["stage"]), s["sliders"], self._part_stats(), self._mode())

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

    def _restamp_and_rescore(self, physics: bool) -> None:
        for e in self.archive.values():
            if not self._current(e) or e.status not in ("VALIDATED", "FINAL"):
                continue
            if physics:
                self._compute_physics(e)
            e.revs = {k: self.store.revs[k] for k in ("parts_rev", "constraint_rev", "mass_rev", "weights_rev")}
            self._score_entry(e)
        self._select_best()

    # =========================================================================================== scoring
    def _weights(self) -> dict:
        s = self.store.settings
        return slider_weights(s["sliders"], int(s["stage"]), "default")

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
               "G": n.get("G"), "H": n.get("H"), "C": n.get("C")}
        return g, out

    def _score_entry(self, e: LayoutEntry) -> None:
        e.g, e.normalised = self._score_raw(e.raw)
        e.norm_epoch = self._norm().epoch

    def _compute_physics(self, e: LayoutEntry) -> None:
        phys = self._phys()
        items, excluded = [], []
        for pid, o, t in e.poses:
            p = phys.get(pid)
            if p is None:
                excluded.append(pid)
                continue
            r = ROTATIONS_F[o]
            items.append((p.mass_kg, r @ p.com_can_mm + t, r @ p.inertia_com_kgm2 @ r.T))
        m = dict(e.geo)
        m["mass_excluded_parts"] = excluded
        raw = {"L": e.geo["length_used_mm"], "span": e.geo["span_mm"]}
        if "margin_objective" in e.geo and e.stage == 2:
            raw["G"] = e.geo["margin_objective"]
        if items:
            a = assembly([], [], np.zeros((0, 3)), items)
            im = inertia_metrics(a.inertia_kgm2)
            cb = com_box_check(a.com_mm, self._target())
            m.update({"mass_kg": a.mass_kg, "com_mm": a.com_mm.tolist(), "inertia_kgm2": a.inertia_kgm2.tolist(), **im, **cb})
            if e.stage == 2:
                fm, fc, fi = s2.frame_mass_props()
                m["frame_mass_kg"] = fm
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
                excess = np.maximum(np.abs(a.com_mm) - np.array([20.0, 20.0, 70.0]), 0)
                e.cv = float(excess.sum() / 10.0)
        m.setdefault("insertion_order", None)
        m.setdefault("interlocked", [])
        m.setdefault("cable_blocked_fraction", None)
        m.setdefault("hardware_cost_rel", None)
        e.metrics = jsonable(m)
        e.raw = raw

    def _select_best(self) -> None:
        cur = [e for e in self.archive.values() if self._current(e) and e.status in ("VALIDATED", "FINAL")]
        if not cur:
            self.best_id = None
            return
        best = min(cur, key=lambda e: (e.cv, e.g, e.raw.get("L", math.inf), e.id))
        if best.id != self.best_id:
            self.best_id = best.id

    def _maybe_new_epoch(self, force: bool = False) -> None:
        if self.ctx is None:
            return
        norm = self._norm()
        raws = [e.raw for e in self.archive.values() if self._current(e) and e.status in ("VALIDATED", "FINAL")]
        raws += self.raw_pool.get(self.ctx.ctx_id, [])[-300:]
        raws = [r for r in raws if "D" in r]
        if len(raws) < 10:
            return
        if not force and norm.utopia:
            # only when some value fell outside the current range by > 5 % of it
            out = False
            for k in ("L", "D", "T", "P"):
                if k not in norm.utopia:
                    continue
                lo, hi = norm.utopia[k], norm.nadir[k]
                span = hi - lo
                vals = [r[k] for r in raws if k in r]
                if vals and (min(vals) < lo - 0.05 * span or max(vals) > hi + 0.05 * span):
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
        if status == "SEARCHING" and self.run_status != "SEARCHING":
            self.last_improve = time.monotonic()
            if self.search_t0 is None:
                self.search_t0 = time.monotonic()
        self.run_status, self.status_detail = status, detail
        self.broadcast("status", {"run_status": status, "detail": detail})

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
            self.val_queue.sort(key=lambda x: x[0])
            item = self.val_queue.pop(0)
            ctx_id = item[5]
            w = next((w for w in idle if w.ctx_id == ctx_id), None)
            if w is None:
                if self.ctx is not None and ctx_id != self.ctx.ctx_id:
                    self.pending_hashes.discard(item[1])
                    continue                  # older inputs: nobody can validate it any more
                self.val_queue.insert(0, item)
                break
            idle.remove(w)
            self.job_counter += 1
            w.busy, w.job = True, self.job_counter
            self.val_pending[w.job] = item
            w.cmd_q.put(("validate", w.job, ctx_id, item[2], False, bool(item[8])))

    def _migrate(self) -> None:
        if self.ctx is None or self.best_id is None:
            return
        best = self.archive[self.best_id]
        if best.keys is None:
            return
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
        pool = self.raw_pool.setdefault(ctx_id, [])
        cur = [e for e in self.archive.values() if self._current(e) and e.status in ("VALIDATED", "FINAL")]
        for c in cands:
            if c["unplaced"]:
                continue
            raw, cv = self.ev.raw_from_poses(c["poses"], c["unplaced"])
            if cv > 0:
                continue
            pool.append(raw)
            g, nrm = self._score_raw(raw)
            if w.best_g is None or g < w.best_g:
                w.best_g = g
            h = layout_hash(self.ctx.stage, c["poses"])
            if best_cand is None or g < best_cand[0]:
                best_cand = (g, h, c, raw, nrm)
            if h in self.by_hash or h in self.pending_hashes:
                continue
            keys3 = ("L", "D", "T")
            nondom = all(k in raw for k in keys3) and not any(
                all(k in e.raw for k in keys3) and dominates(e.raw, raw, keys3) for e in cur)
            if g < best_g_now - 1e-12 or nondom:
                self.pending_hashes.add(h)
                # a would-be new best from the box decoder also gets certified drop compaction
                compact = g < best_g_now - 1e-12 and w.plan.get("decoder") == "box"
                self.val_queue.append((g, h, c["poses"], raw, np.asarray(c["keys"]).tolist(), ctx_id,
                                       (self.ctx.parts_sig, self.ctx.constraint_sig, self.ctx.stage, self.ctx.spec_sig),
                                       self._algo_for(w), compact))
        if len(pool) > 2000:
            del pool[:1000]
        if len(self.val_queue) > 24:
            self.val_queue.sort(key=lambda x: x[0])
            for item in self.val_queue[24:]:
                self.pending_hashes.discard(item[1])
            del self.val_queue[24:]
        now = time.monotonic()
        if best_cand is not None and now - self.last_candidate > CANDIDATE_EVERY_S and \
                any(c.want_candidates for c in self.clients):
            self.last_candidate = now
            g, h, c, raw, nrm = best_cand
            self.candidate = self._candidate_json(h, c["poses"], raw, g, nrm)
            self.broadcast("layout.candidate", {"layout": self.candidate}, only=lambda cl: cl.want_candidates)
        self._dispatch()
        self._dispatch_validation()

    def _on_validated(self, wid, job, ctx_id, summary, extra=None) -> None:
        w = self.workers[wid]
        w.busy = False
        item = self.val_pending.pop(job, None)
        if item is None:
            return
        g, h, poses, raw, keys, item_ctx, sigs, algo, _compact = item
        self.pending_hashes.discard(h)
        if summary is None:                    # the validator had switched context: retry if still relevant
            if self.ctx is not None and item_ctx == self.ctx.ctx_id:
                self.pending_hashes.add(h)
                self.val_queue.append(item)
            return
        decoded_hash = h
        algo = dict(algo)
        if extra and extra.get("poses"):
            poses = extra["poses"]
            h = layout_hash(sigs[2], poses)
            algo["detail"] += " + certified drop compaction"
            algo["compaction"] = {"moved_mm": {k: v for k, v in extra["moved_mm"].items() if v > 0},
                                  "seconds": extra["seconds"]}
        geo = self._geo_metrics(poses, summary, sigs[2])
        n = self.store.next_id("layout")
        e = LayoutEntry(id=f"L-{n:04d}", hash=h, stage=sigs[2], mode="default", algorithm=algo,
                        status="VALIDATED" if summary["valid"] else "REJECTED", parts_sig=sigs[0], constraint_sig=sigs[1],
                        poses=[(pid, int(o), np.asarray(t, float)) for pid, o, t in poses], geo=geo,
                        validation={"certified": bool(summary["valid"]), "validator_version": summary["validator_version"],
                                    "tolerance_mm": 0.001, "pairs": summary["pairs"], "statics": summary["statics"],
                                    "levels": summary["levels"], "min_clearance_mm": summary["min_clearance_mm"],
                                    "seconds": summary["seconds"], "checked_at": now_iso(),
                                    "violations": summary["violations"]},
                        keys=keys, spec_sig=sigs[3])
        if not summary["valid"]:
            self._error(f"validator rejected decoder layout {e.id}: {summary['violations'][:3]}")
        self._compute_physics(e)
        e.revs = {k: self.store.revs[k] for k in ("parts_rev", "constraint_rev", "mass_rev", "weights_rev")}
        self._score_entry(e)
        self.archive[e.id] = e
        self.by_hash[h] = e.id
        self.by_hash[decoded_hash] = e.id
        self._persist(e)
        if not self._current(e) or e.status != "VALIDATED":
            return
        prev = self.best_id
        prev_g = self.archive[prev].g if prev else math.inf
        self._select_best()
        if self.best_id != prev:
            if e.g < prev_g - 1e-9 * max(1.0, abs(prev_g)):
                self.last_improve = time.monotonic()
            self._publish_best("search")
            self.best_g_hist.append((time.monotonic(), e.g))
            if self.best_id == e.id and "slab" not in algo.get("detail", ""):
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
            self.val_queue.append((g, h, cand, raw, e.keys, self.ctx.ctx_id, sigs, algo, False))

    def _geo_metrics(self, poses, summary, stage: int) -> dict:
        tops, bottoms, vol = [], [], 0.0
        for pid, o, t in poses:
            hw = to_world(self.geoms[pid].hull_pts, o, np.asarray(t, float))
            tops.append(hw[:, 2].max())
            bottoms.append(hw[:, 2].min())
            vol += self.records[pid].volume_mm3 or 0.0
        z0 = float(ENCLOSURE_LO[2])
        req = s2.C_PP if stage == 2 else 0.0
        mc = summary["min_clearance_mm"]
        slack = max(0.0, (mc if mc is not None and math.isfinite(mc) else 5.0) - req)
        return jsonable({
            "length_used_mm": float(max(tops) - z0), "span_mm": float(max(tops) - min(bottoms)),
            "free_length_mm": float(ENCLOSURE_HI[2] - max(tops)),
            "space_used": float(vol / float(np.prod(ENCLOSURE_HI - ENCLOSURE_LO))), "parts_placed": len(poses),
            "min_clearance_mm": mc, "required_clearance_mm": req, "margin_objective": float(1.0 - min(1.0, slack / 5.0)),
            "largest_empty_box_mm": [100.0, 100.0, float(ENCLOSURE_HI[2] - max(tops))] if stage == 1 else None,
        })

    # =========================================================================================== publishing
    def _publish_best(self, source: str, force: bool = False) -> None:
        if self.best_id is None:
            return
        e = self.archive[self.best_id]
        self.broadcast("layout.validated", {"layout": self.layout_json(e), "source": source})

    def _progress(self) -> dict:
        best = self.archive.get(self.best_id) if self.best_id else None
        return jsonable({
            "status": self.run_status, "evaluations": self.evaluations, "best_g": best.g if best else None,
            "best_length_mm": best.raw.get("L") if best else None,
            "elapsed_s": time.monotonic() - self.search_t0 if self.search_t0 else 0.0,
            "validation_queue": len(self.val_queue), "validating": len(self.val_pending),
            "archive": sum(1 for e in self.archive.values() if self._current(e)),
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

    def layout_json(self, e: LayoutEntry, full: bool = True) -> dict:
        d = {
            "id": e.id, "hash": e.hash, "stage": e.stage, "mode": e.mode, "status": e.status,
            **{k: e.revs.get(k, 0) for k in ("parts_rev", "constraint_rev", "mass_rev", "weights_rev")},
            "metrics": e.metrics,
            "scores": {"normalised": e.normalised, "g": _f(e.g), "norm_epoch": e.norm_epoch},
            "algorithm": e.algorithm, "validation": e.validation, "origin": e.origin, "created": e.created,
            "part_ids": [p[0] for p in e.poses], "current": self._current(e),
        }
        if full:
            d["poses"] = self.pose_json(e.poses)
            d["extra_items"] = []
        return jsonable(d)

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
        return jsonable({
            "name": self.store.name,
            "enclosure": {"size_mm": [100.0, 100.0, 340.5], "min_mm": ENCLOSURE_LO.tolist(), "max_mm": ENCLOSURE_HI.tolist(),
                          "form": "3U CubeSat, CDS Rev 14.1 envelope"},
            "rotations": [np.asarray(m).reshape(3, 3).tolist() for m in as_lists()],
            "parts": self.part_list(),
            "settings": self.store.settings,
            "stage2_frame": {"status": "ASSUMED", "wall_mm": s2.WALL, "inner_box_mm": (hi - lo).tolist(),
                             "rail_mm": [s2.RAIL, s2.RAIL], "boxes": frame_boxes,
                             "walls": {"inner_min": lo.tolist(), "inner_max": hi.tolist()},
                             "frame_mass_kg": fm, "frame_com_mm": fc.tolist(),
                             "note": "harness channel interrupted across the PCB stack (U5 default); PCB stack macro "
                                     "and rods arrive with M7"},
            "limits": {"com_box_mm": [20.0, 20.0, 70.0], "cds_mass_note_kg": 6.0, "clearance_part_mm": s2.C_PP,
                       "clearance_wall_mm": s2.C_WALL, "length_mm": 340.5, "cable_mode_threshold": 70},
            "revs": self.revs,
            "dataset_sha256": self.store.dataset_sha256,
            "building": building,
            "inbox": str(self.store.inbox),
            "fusion360": "NOT_CONFIGURED",
        })

    def snapshot(self) -> dict:
        best = self.archive.get(self.best_id) if self.best_id else None
        return {"project": self.project_json(), "best_validated": self.layout_json(best) if best else None,
                "candidate": self.candidate, "run_status": self.run_status, "selector": self.selector()}

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
        out = sweep(int(s["stage"]), s["sliders"], self._part_stats(), slider, self._mode())
        out["current"] = s["sliders"][slider]
        out["rule"] = "default rule — no benchmark evidence yet"
        return out

    def selector_map(self, x: str, y: str, n: int) -> dict:
        s = self.store.settings
        for k in (x, y):
            if k not in s["sliders"]:
                raise ValueError(f"unknown slider {k!r}")
        out = grid_map(int(s["stage"]), s["sliders"], self._part_stats(), x, y, max(2, min(int(n), 101)), self._mode())
        out["current"] = [s["sliders"][x], s["sliders"][y]]
        return out

    def pareto(self) -> dict:
        cur = [e for e in self.archive.values() if self._current(e) and e.status in ("VALIDATED", "FINAL")
               and e.normalised.get("L") is not None and e.normalised.get("D") is not None
               and e.normalised.get("I") is not None]
        pts = []
        if cur:
            a = np.array([[e.normalised["L"], e.normalised["D"], e.normalised["I"]] for e in cur], float)
            le = np.all(a[None, :, :] <= a[:, None, :], axis=2)       # [i, j]: j is no worse than i everywhere
            lt = np.any(a[None, :, :] < a[:, None, :], axis=2)
            dominated = np.any(le & lt, axis=1)
            for e, d in zip(cur, dominated):
                if d:
                    continue
                pts.append({"layout_id": e.id, "L": e.raw.get("L"), "D": e.raw.get("D"), "I": e.normalised["I"],
                            "T": e.raw.get("T"), "P": e.raw.get("P"), "L_norm": e.normalised["L"],
                            "D_norm": e.normalised["D"], "g": e.g})
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
    def _persist(self, e: LayoutEntry) -> None:
        with open(self.store.archive_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(e.to_store()) + "\n")

    def _rewrite_archive(self) -> None:
        tmp = self.store.archive_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for e in self.archive.values():
                fh.write(json.dumps(e.to_store()) + "\n")
        tmp.replace(self.store.archive_path)

    def _load_archive(self) -> None:
        if not self.store.archive_path.exists():
            return
        for line in self.store.archive_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = LayoutEntry.from_store(json.loads(line))
            except Exception:  # noqa: BLE001 - an entry from an older format: skip it
                continue
            self.archive[e.id] = e
            self.by_hash[e.hash] = e.id

    # =========================================================================================== edits
    def apply_settings(self, new: dict) -> None:
        s = self.store.settings
        old_stage = int(s.get("stage", 1))
        old_target = list(s.get("target_com_mm", [0, 0, 0]))
        for k in ("stage", "target_com_mm", "compactness_definition", "show_frame_mass_in_com"):
            if k in new and new[k] is not None:
                s[k] = new[k]
        if "sliders" in new and isinstance(new["sliders"], dict):
            for k, v in new["sliders"].items():
                if k in s["sliders"] and v is not None:
                    s["sliders"][k] = float(np.clip(float(v), 0, 100))
        s["stage"] = 2 if int(s.get("stage", 1)) == 2 else 1
        self._bump("weights_rev")
        if int(s["stage"]) != old_stage:
            self._refresh_inputs(f"stage {s['stage']} selected", bump_parts=False)
        else:
            if list(s.get("target_com_mm", [0, 0, 0])) != old_target and self.ev is not None:
                self.ev.target = np.asarray(self._target(), float)
                for w in self.workers:
                    if w.role == "island" and self.ctx is not None:
                        w.cmd_q.put(("phys", self.ctx.ctx_id, self.store.revs["mass_rev"], self._phys_wire(),
                                     self._target()))
            self._restamp_and_rescore(physics=list(s.get("target_com_mm")) != old_target)
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
        if self.run_status == "CONVERGED" and self.ctx is not None:
            self._set_status("SEARCHING", "goals changed")

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
                self.ev.phys = self._phys()
            for w in self.workers:
                if w.role == "island" and self.ctx is not None:
                    w.cmd_q.put(("phys", self.ctx.ctx_id, self.store.revs["mass_rev"], self._phys_wire(), self._target()))
            prev = self.best_id
            self._restamp_and_rescore(physics=True)
            if prev is not None and prev in self.archive:
                self.broadcast("metrics.update", {"layout_id": prev, "metrics": self.archive[prev].metrics})
            if self.best_id != prev:
                self._publish_best("archive")
            if self.run_status == "CONVERGED":
                self._set_status("SEARCHING", "masses changed")
        else:
            self._bump("parts_rev")
            self._restamp_and_rescore(physics=False)
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
            fut = self.ladder_pool.submit(ladder_job, str(snap), pid, dict(self.store.settings["sliders"]), str(path),
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
                self.search_t0 = time.monotonic()
                self._set_status("SEARCHING", "re-run with new random seeds")
        elif action == "reset":
            self.archive = {k: v for k, v in self.archive.items() if v.status == "FINAL"}
            self.by_hash = {v.hash: k for k, v in self.archive.items()}
            self._rewrite_archive()
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
        if e.stage == 2:
            spec = s2.stage2_spec(stage2_config({pid: self.records[pid] for pid, _, _ in e.poses}))
        else:
            spec = StageSpec(1, ENCLOSURE_LO.copy(), ENCLOSURE_HI.copy(), 0.0, 0.0)
        geoms = {pid: self.geoms[pid] for pid, _, _ in e.poses}
        rep = Validator(geoms).validate(e.poses, spec, want_planes=True)
        cert = build_certificate(e.id, rep, self.records, e.poses, spec, self._files_for(e.poses),
                                 extra={"layout_hash": e.hash, "app_version": VERSION})
        from ..optimise.bounds import lower_bounds
        lbs = lower_bounds([self.records[pid] for pid, _, _ in e.poses])
        metrics = dict(e.metrics)
        metrics["lower_bounds"] = [(f"{b['name']} (valid for {b['valid_for']})", b["value_mm"], b["why"])
                                   for b in lbs if b.get("value_mm") is not None]
        md = proof_markdown(cert, rep, metrics)
        out = {"markdown": md, "certificate": cert, "valid": rep.valid}
        self.proof_cache[key] = out
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
        self._rewrite_archive()
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
