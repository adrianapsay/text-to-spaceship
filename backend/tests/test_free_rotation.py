"""Free-rotation experiment (Stage 1, research): exact checks, drop, and a run whose poses re-check independently."""
import fcl
import numpy as np
import pytest

from t2s.collision.geom import part_geom_from_record
from t2s.core.rotations import ROTATIONS_F
from t2s.experiments.free_rotation import GAP, Scene, _rot, angle_from_axis_aligned, run_free_rotation
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO

NAMES = ["battery_pack", "payload_electronics_box", "wedge_bracket", "irregular_blob", "sensor_housing_hex"]
I0 = ROTATIONS_F[0]


@pytest.fixture(scope="module")
def geoms(dataset_parts):
    return {n: part_geom_from_record(dataset_parts[n][1]) for n in NAMES}


def _stack(geoms, gap):
    """Axis-aligned start: each part in its flattest orientation that fits sideways, stacked along +Z."""
    poses, z = [], float(ENCLOSURE_LO[2])
    for n in NAMES:
        ob = geoms[n].orient_bounds
        ok = [o for o in range(24) if ob[o][3] - ob[o][0] <= 100 and ob[o][4] - ob[o][1] <= 100]
        o = min(ok, key=lambda k: ob[k][5] - ob[k][2])
        b = ob[o]
        t = np.array([-0.5 * (b[0] + b[3]), -0.5 * (b[1] + b[4]), z - b[2]])
        poses.append((n, o, t))
        z = t[2] + b[5] + gap
    return poses


def test_angle_from_axis_aligned():
    assert all(angle_from_axis_aligned(R) < 1e-6 for R in ROTATIONS_F)
    assert angle_from_axis_aligned(_rot([0, 0, 1], np.radians(30.0)) @ ROTATIONS_F[5]) == pytest.approx(30.0, abs=1e-6)


def test_exact_check_overlap_tilt_envelope_and_drop(geoms):
    a, b = "lower", "upper"                             # two battery packs: identical footprints
    g = geoms["battery_pack"]
    ba = bb = g.orient_bounds[0]
    ta = np.array([0.0, 0.0, -100.0])
    touch = ta[2] + ba[5] - bb[2]                       # b resting on a
    sc = Scene({a: g, b: g}, {a: (I0, ta), b: (I0, np.array([0.0, 0.0, 100.0]))})
    assert sc.part_ok(b, I0, np.array([0.0, 0.0, touch + 0.01]))
    assert not sc.part_ok(b, I0, np.array([0.0, 0.0, touch - 0.5]))
    ext = ba[3:] - ba[:3]
    axis = [1, 0, 0] if ext[1] >= ext[0] else [0, 1, 0]            # tilt so the long side dips
    th = np.radians(20.0)
    assert max(ext[0], ext[1]) / 2 * np.sin(th) - ext[2] / 2 * (1 - np.cos(th)) > 1.0   # the edge really dips
    assert not sc.part_ok(b, _rot(axis, th) @ I0, np.array([0.0, 0.0, touch + 0.01]))
    assert not sc.part_ok(b, I0, np.array([60.0, 0.0, 100.0]))           # outside the envelope
    z = sc.drop(b, I0, np.array([0.0, 0.0, 100.0]))
    assert z is not None and touch + GAP - 1e-9 <= z[2] <= touch + 0.1


def test_run_keeps_every_pose_valid_and_never_gets_longer(geoms):
    start = _stack(geoms, gap=12.0)
    res = run_free_rotation(geoms, start, budget_s=15.0, seed=3)
    assert res["start_valid"] and res["valid"]
    assert res["accepted_moves"] >= 1 and res["improvement_mm"] > 0
    assert res["length_used_mm"] == pytest.approx(res["start_length_mm"] - res["improvement_mm"])
    # independent re-check of the final poses: envelope on every vertex, no mesh intersection, no nesting
    poses = {p["part_id"]: (np.array(p["R"]), np.array(p["t_mm"])) for p in res["poses"]}
    objs = {}
    for n, (R, t) in poses.items():
        w = geoms[n].v @ R.T + t
        assert np.all(w >= ENCLOSURE_LO - 1e-9) and np.all(w <= ENCLOSURE_HI + 1e-9)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9) and np.linalg.det(R) == pytest.approx(1.0)
        objs[n] = fcl.CollisionObject(geoms[n].fcl_model(), fcl.Transform(R, t))
    for i, a in enumerate(NAMES):
        for b in NAMES[i + 1:]:
            assert fcl.collide(objs[a], objs[b], fcl.CollisionRequest(), fcl.CollisionResult()) == 0, (a, b)
    top = max(float((geoms[n].v @ R.T + t)[:, 2].max()) for n, (R, t) in poses.items())
    assert top - ENCLOSURE_LO[2] <= res["length_used_mm"] + 1e-6
