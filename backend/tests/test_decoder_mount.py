"""V2: bracket-aware placement in the box decoder (MountSpec) and the Stage 2 model that uses it."""
import json
from pathlib import Path

import numpy as np
import pytest

from t2s.core import formfactor
from t2s.decoders.box_decoder import BoxDecoder, MountSpec, ProxyPart

LO, HI = np.array([-100.0, -50.0, -100.0]), np.array([100.0, 50.0, 100.0])
REACH = 40.0


def _part(pid, size, pad_x=False):
    """A box part (canonical frame at its min corner); with pad_x, a 1.8 mm mounting layer on its +x face."""
    x, y, z = size
    boxes = [[0, 0, 0, x, y, z]]
    if pad_x:
        boxes.append([x, 0, 0, x + 1.8, y, z])
    return ProxyPart(pid, np.array(boxes, float), [0]), ([x, 0, 0, x + 1.8, y, z], 0, 1)


def _decoder(parts, pads, mount=True):
    spec = MountSpec(pads=pads, walls=np.array([LO[0], HI[0], LO[1], HI[1], LO[2], HI[2]]), reach=REACH,
                     clearance=1.2, targets=[]) if mount else None
    return BoxDecoder(parts, LO, HI, 2.2, 0.1, mixed_candidates=True, mount=spec)


def test_a_part_is_placed_where_its_bracket_reaches_a_wall_and_its_corridor_stays_free():
    a, pad = _part("a", (20, 20, 20), pad_x=True)
    fillers = [_part(f"f{k}", (30, 30, 30))[0] for k in range(6)]
    parts = [a] + fillers
    order = list(range(len(parts)))
    # geometry only: packed into the −x corner, its mounting side 170 mm from the +x wall it faces
    plain = _decoder(parts, {"a": pad}, mount=False).decode(order, np.zeros(len(parts)), np.zeros(len(parts)))
    t_plain = {p: t for p, _, t in plain.poses}["a"]
    assert HI[0] - (t_plain[0] + 20.0) > REACH
    # bracket-aware: against the +x wall (within reach), with its corridor reserved and kept clear by the fillers
    res = _decoder(parts, {"a": pad}).decode(order, np.zeros(len(parts)), np.zeros(len(parts)))
    t = {p: t for p, _, t in res.poses}["a"]
    side = t[0] + 20.0
    assert 0.0 <= HI[0] - side <= REACH
    assert len(res.corridors) == 1
    c = res.corridors[0]
    assert c[0] <= side + 0.2 and c[3] >= HI[0] - 0.2               # from the part side to the wall
    for pid, _, tf in res.poses:
        if pid == "a":
            continue
        lo_f, hi_f = tf - 1.1, tf + 30.0 + 1.1                      # filler boxes as the decoder inflates them
        assert np.any(hi_f <= c[:3] + 1e-9) or np.any(lo_f >= c[3:] - 1e-9), pid
    # the returned placed boxes are parts only (corridors are reported separately)
    assert len(res.placed_boxes) == 1 + 1 + len(fillers)            # a (body + layer) + fillers


def test_geometry_only_decoders_are_unchanged_by_the_mount_code():
    a, pad = _part("a", (20, 20, 20), pad_x=True)
    parts = [a] + [_part(f"f{k}", (30, 30, 30))[0] for k in range(4)]
    order = list(range(len(parts)))
    r1 = _decoder(parts, {}, mount=False).decode(order, np.zeros(len(parts)), np.zeros(len(parts)))
    r2 = _decoder(parts, {"a": pad}, mount=False).decode(order, np.zeros(len(parts)), np.zeros(len(parts)))
    assert [(p, o, list(t)) for p, o, t in r1.poses] == [(p, o, list(t)) for p, o, t in r2.poses]
    assert len(r1.corridors) == 0


@pytest.fixture
def six_u():
    formfactor.set_form_factor("6U")
    yield
    formfactor.set_form_factor("3U")


def _synthetic(scale):
    from t2s.parts.build import build_part
    from t2s.parts.scale import scale_part
    from t2s.service.project import suggest_tags
    data = Path(__file__).resolve().parents[2] / "data" / "synthetic"
    man = json.loads((data / "manifest.json").read_text())
    recs = {}
    for p in man["parts"]:
        if p["role"] == "packable":
            r = build_part((data / p["file"]).read_bytes(), p["name"], p["name"], file=p["file"])
            r.tags = suggest_tags(p["name"])
            recs[p["name"]] = scale_part(r, scale)
    return recs


def test_stage2_bracket_aware_decoding_mounts_far_more_parts_and_rods_follow_the_boards(six_u):
    """6U at 50 % part size (the case that never found a feasible layout): random chromosomes decode to layouts
    with far fewer unmounted parts once placement is bracket-aware; the PC/104 rods scale with the boards and are
    obstacles of the decoder, so no part is packed against them."""
    from t2s.constraints import stage2 as s2
    from t2s.constraints.stage2_model import Stage2Model
    recs = _synthetic(0.5)
    rng = np.random.default_rng(5)
    keys = [rng.random(3 * len(recs) + 3) for _ in range(12)]
    counts = {}
    for on in (True, False):
        model = Stage2Model(recs, "default", am_allowed=True)
        if not on:
            model._mount_spec = lambda n: None
        n = model.n
        un = []
        for k in keys:
            res = model.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
            un.append(len(res.meta["unmounted"]) + len(res.unplaced))
            if on:
                assert res.meta["rod_xy"] == pytest.approx(0.5 * s2.ROD_XY)
                rods = [s for s in model.statics(res.meta) if s.kind == "rod"]
                assert len(rods) == 4 and all(abs(abs(s.corners[:, 0].mean()) - 0.5 * s2.ROD_XY) < 1e-9 for s in rods)
        counts[on] = un
    assert np.mean(counts[True]) < 0.5 * np.mean(counts[False])
    assert min(counts[True]) == 0 < min(counts[False])


def test_bracket_budget_steps():
    from t2s.mfg.rules import AM_FACTOR, am_level
    assert [am_level(b) for b in (0, 1, 33, 34, 50, 66, 67, 99, 100)] == [0, 1, 1, 2, 2, 2, 3, 3, 4]
    assert AM_FACTOR[1] == 1.0 < AM_FACTOR[2] < AM_FACTOR[3] < AM_FACTOR[4] == float("inf")


def test_a_higher_bracket_budget_chooses_more_metal_am_brackets_but_keeps_direct_mounts(six_u):
    """"0 = simple, 100 = 3D printed": the same chromosomes decoded at budget steps 0, 1, 2 and 4 — no metal AM at
    0; more of it at each higher step; a part bolted straight to its wall keeps its fasteners even at 100."""
    from t2s.constraints.stage2_model import Stage2Model
    recs = _synthetic(0.5)
    rng = np.random.default_rng(11)
    keys = [rng.random(3 * len(recs) + 3) for _ in range(6)]
    am, direct = {}, {}
    for level in (0, 1, 2, 4):
        model = Stage2Model(recs, "default", am_level=level)
        n = model.n
        kinds = []
        for k in keys:
            res = model.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
            kinds += [b["kind"] for b in res.meta["brackets"]]
        am[level], direct[level] = kinds.count("metal_am"), kinds.count("direct")
    assert am[0] == 0
    assert am[1] <= am[2] < am[4]
    assert direct[4] > 0 and abs(direct[4] - direct[1]) <= 0.2 * direct[1]
