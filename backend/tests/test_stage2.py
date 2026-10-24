"""M7: Stage 2 model — PC/104 stack, harness modes, edge boards on standoffs, mounting, validation under each
layout's own rules (protocol §O.2, Addenda 1.4 and 2.3)."""
import copy

import numpy as np
import pytest

from t2s.collision.geom import part_geom_from_record, to_world
from t2s.collision.validate import Validator, plane_certificate
from t2s.constraints import stage2 as s2
from t2s.constraints.stage2_model import (
    PAD,
    ROD_MODEL,
    STACK_OFFSET_MAX,
    Stage2Model,
    corridor_box,
    mode_for,
    stack_rods,
)
from t2s.service.worker import insertion_check


@pytest.fixture(scope="module")
def recs(dataset_parts):
    out = {}
    for n, (p, r) in dataset_parts.items():
        if p["role"] != "packable":
            continue
        c = copy.copy(r)                    # shallow copy: same geometry, own id and tags
        c.id, c.tags = n, (["pcb"] if n.startswith("pcb") else [])
        out[n] = c
    return out


@pytest.fixture(scope="module")
def val(recs):
    return Validator({i: part_geom_from_record(r) for i, r in recs.items()})


def test_cable_slider_modes():
    assert mode_for(0) == "default" and mode_for(1) == "soft" and mode_for(69.9) == "soft"
    assert mode_for(70) == "continuous" and mode_for(100) == "continuous"


@pytest.mark.parametrize("mode", ["default", "soft", "continuous"])
def test_every_decode_is_certified_under_its_own_rules(recs, val, mode):
    m = Stage2Model(recs, mode)
    n = m.n
    rng = np.random.default_rng({"default": 1, "soft": 2, "continuous": 3}[mode])
    for _ in range(4):
        k = rng.random(m.dim)
        r = m.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
        if r.unplaced:
            continue
        rep = val.validate(r.poses, m.spec(r.meta, relaxed=r.meta["overflow_mm"] > 0))
        assert rep.valid, (mode, rep.violations[:3])
        # poses use the parts' own (symmetry-reduced) orientations
        assert all(o in recs[pid].allowed_orients for pid, o, _ in r.poses)


def test_pc104_stack_is_flat_centred_and_pitched(recs):
    m = Stage2Model(recs, "default")
    lo, hi = s2.inner_box()
    for key, end in ((0.0, "-z"), (0.4, "-z"), (0.5, "+z"), (0.9, "+z")):
        poses, block, span = m.stack_layout(key)
        zs = []
        for pid, o, t in poses:
            b = recs[pid].orient_bounds[o]
            ext = b[3:] - b[:3]
            assert ext[2] == pytest.approx(ext.min())                       # flat: thinnest along Z
            c = 0.5 * (b[:3] + b[3:]) + t
            assert abs(c[0]) < 1e-3 and abs(c[1]) < 1e-3                       # centred on the enclosure axis
            zs.append(b[2] + t[2])
        assert np.diff(sorted(zs)) == pytest.approx(s2.PCB_PITCH, abs=2e-3)
        # anchored at the end plate the key chooses, the offset beyond the wall clearance as the key asks
        assert m.stack_place(key)[0] == end
        gap = span[0] - lo[2] if end == "-z" else hi[2] - span[1]
        assert gap - m.wall_gap == pytest.approx(m.stack_place(key)[1], abs=2e-3)
        meta = {"mode": "default", "stack_span": span, "stack_block": block.tolist(), "rod_end": end}
        st = {s.name: s for s in m.statics(meta)}
        for r in ("rod++", "rod+-", "rod-+", "rod--"):        # rods from the end plate through every board
            c = st[r].corners
            assert (c[:, 2].min(), c[:, 2].max()) == pytest.approx((lo[2], span[1]) if end == "-z" else (span[0], hi[2]))
            assert np.ptp(c[:, 0]) == pytest.approx(s2.ROD_KEEP) and np.ptp(c[:, 1]) == pytest.approx(s2.ROD_KEEP)
        if key in (0.4, 0.9):                                  # off the plate: the harness runs on both sides
            h0, h1 = st["harness0"].corners, st["harness1"].corners
            assert h0[:, 2].max() < span[0] - s2.C_WALL and h1[:, 2].min() > span[1] + s2.C_WALL   # interrupted


def test_stack_key_keeps_most_stacks_close_to_their_end_plate():
    keys = np.linspace(0.0, 1.0, 2001)[:-1]
    place = [Stage2Model.stack_place(k) for k in keys]
    assert [e for e, _ in place].count("-z") == [e for e, _ in place].count("+z")
    off = np.array([o for _, o in place])
    assert off.min() == 0.0 and off.max() <= STACK_OFFSET_MAX
    assert np.mean(off <= STACK_OFFSET_MAX / 8 + 1e-9) >= 0.5                  # half the keys: within 5 mm
    assert Stage2Model.EXTRA_DEFAULT[0] == 0.0 and Stage2Model.stack_place(0.0) == ("-z", 0.0)


def test_continuous_mode_keeps_corridor_free_and_mounts_boards(recs, val):
    m = Stage2Model(recs, "continuous")
    n = m.n
    rng = np.random.default_rng(7)
    seen_mounted = False
    for _ in range(30):
        # the draw sequence of the original 3n + 2 chromosome (its layouts include a mounted board), COM key 0
        k = np.concatenate([rng.random(m.dim - 1), [0.0]])
        r = m.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
        cb = corridor_box(r.meta["corridor"])
        for pid, o, t in r.poses:                                         # nothing inside the corridor
            b = recs[pid].orient_bounds[o]
            lo, hi = b[:3] + t, b[3:] + t
            assert not (np.all(lo < cb[3:] + s2.C_WALL - 1e-6) and np.all(hi > cb[:3] - s2.C_WALL + 1e-6)), pid
        for pid in ("pcb_obc", "pcb_eps"):
            info = r.meta["mounts"].get(pid)
            if info and info["ok"]:
                seen_mounted = True
                assert "standoffs" in info["how"]
        if r.meta["standoffs"] and not r.unplaced:
            rep = val.validate(r.poses, m.spec(r.meta, relaxed=r.meta["overflow_mm"] > 0))
            assert rep.valid, rep.violations[:3]
            for pid, b in r.meta["standoffs"]:
                length = max(np.asarray(b[3:]) - np.asarray(b[:3]))
                assert 3.0 - 1e-6 <= length <= 50.0 + 1e-6                   # Addendum 2.3 standoff range
    assert seen_mounted


def test_mounting_layer_rule(recs):
    """A part whose padded side faces a wall at the 1.2 mm clearance has its side 3.0 mm away: mountable."""
    m = Stage2Model({"battery_pack": recs["battery_pack"]}, "soft")
    r = m.best_fit_all_orientations([0])
    assert not r.unplaced
    info = r.meta["mounts"]["battery_pack"]
    assert PAD == pytest.approx(1.8)
    assert info["ok"] or "not within reach" in info["how"]


def _decode(m, keys):
    n = m.n
    return m.decode(list(np.argsort(keys[:n], kind="stable")), keys[n:2 * n], keys[2 * n:])


def _com_z(recs, poses):
    from t2s.core.rotations import ROTATIONS_F
    from t2s.objectives.metrics import part_phys
    m = mz = 0.0
    for pid, o, t in poses:
        p = part_phys(recs[pid])
        m += p.mass_kg
        mz += p.mass_kg * (ROTATIONS_F[o][2] @ p.com_can_mm + t[2])
    return mz / m


SHORT = ("battery_pack", "payload_electronics_box", "reaction_wheel", "sensor_housing_hex")


def test_com_shift_brings_a_short_layout_into_the_com_box(recs, val):
    """A short layout packed against the −Z end plate has its COM below the CDS box; the minimal shift (key 0)
    moves the whole layout just inside it, key 1 centres it; both are certified under their own rules."""
    sub = {k: recs[k] for k in SHORT}
    plain = Stage2Model(sub, "soft", relax={"mounting", "com_box"})      # no shift: the decoder's own result
    shifty = Stage2Model(sub, "soft", relax={"mounting"})
    k = np.random.default_rng(5).random(plain.dim)
    r0 = _decode(plain, k)
    assert not r0.unplaced and r0.meta["com_shift_mm"] == 0.0
    z0 = _com_z(sub, r0.poses)
    assert z0 < -70.0                                                    # the problem the shift solves
    for u, check in ((0.0, lambda z: -70.0 < z <= -69.0), (1.0, lambda z: abs(z) < 0.01)):
        k2 = k.copy()
        k2[-1] = u
        r = _decode(shifty, k2)
        z = _com_z(sub, r.poses)
        assert check(z), (u, z)
        assert r.meta["com_shift_mm"] == pytest.approx(z - z0, abs=2e-3)
        assert r.meta["com_z_unshifted_mm"] == pytest.approx(z0, abs=1e-6)
        assert r.meta["overflow_mm"] == 0.0
        assert r.length_top == pytest.approx(r0.length_top + r.meta["com_shift_mm"], abs=1e-6)
        for (pa, oa, ta), (pb, ob, tb) in zip(r0.poses, r.poses):          # one rigid move along Z
            assert pa == pb and oa == ob and np.allclose(tb - ta, [0, 0, r.meta["com_shift_mm"]], atol=1e-6)
        assert val.validate(r.poses, shifty.spec(r.meta)).valid


def test_com_shift_never_costs_a_mount(recs):
    for names, mode in ((SHORT, "soft"), (tuple(recs), "default")):
        sub = {k: recs[k] for k in names}
        plain = Stage2Model(sub, mode, relax={"com_box"})
        shifty = Stage2Model(sub, mode)
        rng = np.random.default_rng(9)
        for _ in range(8):
            k = rng.random(shifty.dim)
            a, b = _decode(plain, k), _decode(shifty, k)
            assert len(b.meta["unmounted"]) <= len(a.meta["unmounted"]), (mode, b.meta["com_shift_mm"])


@pytest.mark.parametrize("key, end", [(0.0, "-z"), (0.5, "+z")])
def test_com_shift_leaves_the_anchored_stack_at_its_end_plate(recs, val, key, end):
    """v2.5: the COM shift moves every part but the PC/104 boards. The stack, its rods (from the end plate through
    every board) and the harness break stay; the shift is scaled by total ÷ moving mass, so the COM still moves as
    far as the key asks; the layout is certified under its own rules."""
    names = ("pcb_obc", "pcb_eps", "battery_pack", "reaction_wheel", "payload_electronics_box")
    sub = {k: recs[k] for k in names}
    plain = Stage2Model(sub, "default", relax={"com_box", "mounting"})
    shifty = Stage2Model(sub, "default", relax={"mounting"})
    k = np.random.default_rng(3).random(plain.dim)
    k[plain.n * 3] = key
    k[-1] = 1.0                                                          # centre the COM as far as the room allows
    a, b = _decode(plain, k), _decode(shifty, k)
    s = b.meta["com_shift_mm"]
    assert s > 0 and not b.unplaced and a.meta["com_shift_mm"] == 0.0
    assert b.meta["rod_end"] == end and b.meta["rod_model"] == ROD_MODEL
    assert b.meta["stack_span"] == a.meta["stack_span"] and b.meta["stack_block"] == a.meta["stack_block"]
    ta, tb = {p: t for p, _, t in a.poses}, {p: t for p, _, t in b.poses}
    for pid in names:
        assert np.allclose(tb[pid] - ta[pid], [0, 0, 0 if pid.startswith("pcb") else s], atol=1e-6), pid
    hw = [(m, c) for _, m, c, _ in shifty.stack_hardware(b.meta)]
    m_all = sum(shifty._phys(p).mass_kg for p in names) + sum(m for m, _ in hw)
    m_move = sum(shifty._phys(p).mass_kg for p in names if not p.startswith("pcb"))
    assert shifty._com_z(b.poses, hw) - shifty._com_z(a.poses, hw) == pytest.approx(s * m_move / m_all, abs=1e-3)
    lo, hi = s2.inner_box()
    st = {x.name: x for x in shifty.statics(b.meta)}
    span = b.meta["stack_span"]
    for r in ("rod++", "rod+-", "rod-+", "rod--"):
        z = st[r].corners[:, 2]
        assert (z.min(), z.max()) == pytest.approx((lo[2], span[1]) if end == "-z" else (span[0], hi[2]))
    harness = [x.corners[:, 2] for x in st.values() if x.kind == "harness"]
    assert all(z.max() < span[0] - s2.C_WALL or z.min() > span[1] + s2.C_WALL for z in harness)   # the break stays
    assert all(f"{end} end plate" in b.meta["mounts"][p]["how"] for p in ("pcb_obc", "pcb_eps"))
    assert len(hw) == 4 and sum(m for m, _ in hw) > 0                    # rods and spacers carry mass …
    assert sum(m for m, _, _ in b.extra_mass) == pytest.approx(sum(m for m, _ in hw))      # … in the layout's physics
    rep = val.validate(b.poses, shifty.spec(b.meta))
    assert rep.valid, rep.violations[:3]


def test_insertion_order_on_a_simple_column(recs):
    sub = {k: recs[k] for k in ("battery_pack", "payload_electronics_box", "reaction_wheel")}
    m = Stage2Model(sub, "soft")
    r = m.best_fit_all_orientations([0, 1, 2])

    class Ctx:
        records = sub
    ins = insertion_check(Ctx, r.poses, r.meta)
    assert ins["order"] is not None and not ins["stuck"]
    assert {p for p, _ in ins["order"]} == set(sub)


def test_assembly_order_directions_and_fixed_items():
    from t2s.constraints.stage2 import assembly_order
    # a above b in one column: a leaves upwards, b downwards
    free = {"+z": {"a": {"b": False}, "b": {"a": True}}, "-z": {"a": {"b": True}, "b": {"a": False}}}
    assert assembly_order(free)[0] is not None
    assert assembly_order(free, {"a": ("-z",), "b": ("+z",)}) == (None, ["a", "b"])     # each only towards the other
    rod = {"+z": {"a": {"b": False, "rod": True}, "b": {"a": True, "rod": False}},
           "-z": {"a": {"b": True, "rod": False}, "b": {"a": False, "rod": True}}, "fixed": ["rod"]}
    assert assembly_order(rod) == (None, ["a", "b"])                                    # a fixed item never leaves


def _column(rec, z_lo):
    o = min(rec.allowed_orients, key=lambda k: rec.orient_bounds[k, 5] - rec.orient_bounds[k, 2])
    b = rec.orient_bounds[o]
    return o, np.array([-(b[0] + b[3]) / 2, -(b[1] + b[4]) / 2, z_lo - b[2]])


def test_insertion_moves_each_part_with_its_bracket(recs):
    """A part goes in fixed to its bracket: a reserved box in another part's way blocks that part, as the part
    itself would (here each box lies on the far side of the other part, so neither can come out)."""
    sub = {k: recs[k] for k in ("battery_pack", "payload_electronics_box")}
    (op, tp), (oq, tq) = _column(sub["battery_pack"], -100.0), _column(sub["payload_electronics_box"], -40.0)
    poses = [("battery_pack", op, tp), ("payload_electronics_box", oq, tq)]

    class Ctx:
        records = sub
    assert insertion_check(Ctx, poses, {})["order"] is not None
    above_q = [-20.0, -20.0, 0.0, 20.0, 20.0, 5.0]
    below_p = [-20.0, -20.0, -130.0, 20.0, 20.0, -125.0]
    meta = {"brackets": [{"name": "bracket:battery_pack", "pid": "battery_pack", "held_parts": ["battery_pack"],
                          "reserve": above_q},
                         {"name": "bracket:payload_electronics_box", "pid": "payload_electronics_box",
                          "reserve": below_p}]}
    ins = insertion_check(Ctx, poses, meta)
    assert ins["order"] is None and ins["stuck"] == sorted(sub)


def test_stack_boards_leave_along_their_rods_away_from_the_end_plate(recs):
    m = Stage2Model(recs, "default")
    rng = np.random.default_rng(12)

    class Ctx:
        records = recs
    seen = set()
    for _ in range(40):
        k = rng.random(m.dim)
        r = _decode(m, k)
        if r.unplaced or r.meta.get("rod_end") in seen:
            continue
        ins = insertion_check(Ctx, r.poses, r.meta)
        if ins["order"] is None:
            continue
        end = r.meta["rod_end"]
        seen.add(end)
        away = "+z" if end == "-z" else "-z"
        assert {u for p, u in ins["order"] if p in m.pcb} == {away}
        # rods run to the other end plate instead: through the parts on that side, which can no longer come out
        flipped = dict(r.meta, rod_end=away)
        crossed = []
        for p, o, t in r.poses:
            h = to_world(recs[p].v[recs[p].hull.vertex_ids], o, t)
            if p not in m.pcb and any(plane_certificate(h, s2.box_corners(rb[:3], rb[3:]))[1] < 0.2
                                      for _, rb in stack_rods(flipped)):
                crossed.append(p)
        if crossed:
            assert set(crossed) <= set(insertion_check(Ctx, r.poses, flipped)["stuck"])
        if len(seen) == 2:
            break
    assert seen, "no decoded layout with an insertion order in 40 random chromosomes"
