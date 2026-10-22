"""M7: Stage 2 model — PC/104 stack, harness modes, edge boards on standoffs, mounting, validation under each
layout's own rules (protocol §O.2, Addenda 1.4 and 2.3)."""
import copy

import numpy as np
import pytest

from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import Validator
from t2s.constraints import stage2 as s2
from t2s.constraints.stage2_model import PAD, Stage2Model, corridor_box, mode_for
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
    poses, block, span = m.stack_layout(0.5)
    zs = []
    for pid, o, t in poses:
        b = recs[pid].orient_bounds[o]
        ext = b[3:] - b[:3]
        assert ext[2] == pytest.approx(ext.min())                       # flat: thinnest along Z
        c = 0.5 * (b[:3] + b[3:]) + t
        assert abs(c[0]) < 1e-3 and abs(c[1]) < 1e-3                       # centred on the enclosure axis
        zs.append(b[2] + t[2])
    assert np.diff(sorted(zs)) == pytest.approx(s2.PCB_PITCH, abs=2e-3)
    st = {s.name: s for s in m.statics({"mode": "default", "stack_span": span, "stack_block": block.tolist()})}
    h0, h1 = st["harness0"].corners, st["harness1"].corners
    assert h0[:, 2].max() < span[0] - s2.C_WALL and h1[:, 2].min() > span[1] + s2.C_WALL   # interrupted at the stack
    assert {"rod++", "rod+-", "rod-+", "rod--"} <= set(st)


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
    from t2s.objectives.metrics import part_phys
    from t2s.core.rotations import ROTATIONS_F
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


def test_shifted_pc104_stack_keeps_its_rules(recs, val):
    names = ("pcb_obc", "pcb_eps", "battery_pack", "reaction_wheel", "payload_electronics_box")
    sub = {k: recs[k] for k in names}
    plain = Stage2Model(sub, "default", relax={"com_box", "mounting"})
    shifty = Stage2Model(sub, "default", relax={"mounting"})
    k = np.random.default_rng(3).random(plain.dim)
    k[plain.n * 3] = 0.0                                                 # stack at the bottom: COM low
    k[-1] = 1.0
    a, b = _decode(plain, k), _decode(shifty, k)
    s = b.meta["com_shift_mm"]
    assert s > 0 and not b.unplaced
    assert b.meta["stack_span"][0] == pytest.approx(a.meta["stack_span"][0] + s, abs=1e-9)
    assert b.meta["stack_block"][5] == pytest.approx(a.meta["stack_block"][5] + s, abs=1e-9)
    st = {x.name: x for x in shifty.statics(b.meta)}
    assert st["rod++"].corners[:, 2].min() == pytest.approx(b.meta["stack_span"][0])     # rods moved with it
    assert st["harness0"].corners[:, 2].max() < b.meta["stack_span"][0] - s2.C_WALL      # harness break too
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
