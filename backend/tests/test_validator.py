"""M2: collision validation (protocol tests T-C). The validator must never accept a true overlap."""
import numpy as np
import pytest

from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import StageSpec, StaticItem, Validator

STAGE1 = StageSpec(1, np.array([-50.0, -50.0, -170.25]), np.array([50.0, 50.0, 170.25]), 0.0, 0.0)


@pytest.fixture(scope="module")
def geoms(dataset_parts):
    return {name: part_geom_from_record(rec) for name, (p, rec) in dataset_parts.items() if rec.volume_mm3}


def stack_poses(geoms, a, b, gap, orient_a=0, orient_b=0):
    """Place b directly above a along +Z with the given face gap (mm)."""
    ba = geoms[a].orient_bounds[orient_a]
    bb = geoms[b].orient_bounds[orient_b]
    ta = np.array([0.0, 0.0, -100.0 - ba[2]])
    top_a = ta[2] + ba[5]
    tb = np.array([0.0, 0.0, top_a + gap - bb[2]])
    return [(a, orient_a, ta), (b, orient_b, tb)]


@pytest.mark.parametrize("gap,ok", [(-1.0, False), (-0.01, False), (-1e-3, False), (0.0, True), (1e-3, True),
                                    (0.01, True), (1.0, True), (2.2, True)])
def test_box_box_gaps_stage1(geoms, gap, ok):
    v = Validator(geoms)
    rep = v.validate(stack_poses(geoms, "battery_pack", "payload_electronics_box", gap), STAGE1)
    assert rep.valid is ok, rep.violations
    if ok:
        assert rep.pairs[0].gap_lb_mm >= gap - 1e-9


@pytest.mark.parametrize("gap,ok", [(1.0, False), (2.19, False), (2.2, True), (3.0, True)])
def test_box_box_gaps_stage2_clearance(geoms, gap, ok):
    spec = StageSpec(2, STAGE1.lo, STAGE1.hi, 2.2, 1.2)
    rep = Validator(geoms).validate(stack_poses(geoms, "battery_pack", "payload_electronics_box", gap), spec)
    assert rep.valid is ok


def test_containment_trap_rod_inside_capsule(geoms):
    """FCL alone sees no surface contact for a rod fully inside the solid capsule; the validator must."""
    cap = geoms["gas_tank_capsule"]
    rod = geoms["magnetorquer_rod"]
    # align both long axes with world Z: pick orientations whose AABB is longest in z
    oc = int(np.argmax(cap.orient_bounds[:, 5] - cap.orient_bounds[:, 2]))
    orr = int(np.argmax(rod.orient_bounds[:, 5] - rod.orient_bounds[:, 2]))
    poses = [("gas_tank_capsule", oc, np.zeros(3)), ("magnetorquer_rod", orr, np.zeros(3))]
    rep = Validator(geoms).validate(poses, STAGE1)
    assert not rep.valid
    assert rep.pairs[0].level == "OVERLAP"


def test_rod_through_torus_hole_is_clear(geoms):
    tor = geoms["magnetometer_ring_torus"]
    rod = geoms["magnetorquer_rod"]
    ot = int(np.argmin(tor.orient_bounds[:, 5] - tor.orient_bounds[:, 2]))     # ring lying flat (axis = Z)
    orr = int(np.argmax(rod.orient_bounds[:, 5] - rod.orient_bounds[:, 2]))    # rod along Z
    poses = [("magnetometer_ring_torus", ot, np.zeros(3)), ("magnetorquer_rod", orr, np.zeros(3))]
    rep = Validator(geoms).validate(poses, STAGE1)
    assert rep.valid, rep.violations
    assert rep.pairs[0].level in ("G3", "G4")
    assert rep.pairs[0].gap_lb_mm >= 5.0            # beyond the 5 mm band only a valid lower bound is reported
    tight = Validator(geoms, tight_band=100.0).validate(poses, STAGE1)
    # analytic: inner radius 22 mm; 8-sector chord at 22·cos(22.5°) = 20.33 mm; rod radius 5 mm -> 15.33 mm
    assert 15.2 < tight.pairs[0].gap_lb_mm <= 17.0


def test_rod_in_tube_bore_is_clear(geoms):
    tube = geoms["optics_baffle_tube"]
    rod = geoms["magnetorquer_rod"]
    ot = int(np.argmax(tube.orient_bounds[:, 5] - tube.orient_bounds[:, 2]))
    orr = int(np.argmax(rod.orient_bounds[:, 5] - rod.orient_bounds[:, 2]))
    poses = [("optics_baffle_tube", ot, np.zeros(3)), ("magnetorquer_rod", orr, np.zeros(3))]
    rep = Validator(geoms).validate(poses, STAGE1)
    assert rep.valid, rep.violations
    tight = Validator(geoms, tight_band=100.0).validate(poses, STAGE1)
    # analytic: bore radius 17 mm; 16-sector chord 17·cos(11.25°) = 16.67 mm; rod radius 5 mm -> 11.67 mm
    assert abs(tight.pairs[0].gap_lb_mm - 11.673) < 0.01


def test_enclosure_containment(geoms):
    poses = [("battery_pack", 0, np.array([45.0, 0.0, 0.0]))]
    rep = Validator(geoms).validate(poses, STAGE1)
    assert not rep.valid and "outside the enclosure" in rep.violations[0]


def test_static_rail_clearance(geoms):
    rail = StaticItem("rail+x+y", np.array([[x, y, z] for x in (41.5, 50) for y in (41.5, 50) for z in (-170, 170)]), "rail")
    spec = StageSpec(2, STAGE1.lo, STAGE1.hi, 2.2, 1.2, [rail])
    # battery 80x80 centred touches x,y up to 40: corner gap to the rail is 1.5 mm in x and y (diagonal 2.12)
    rep = Validator(geoms).validate([("battery_pack", 0, np.zeros(3))], spec)
    assert rep.valid and rep.statics[0].gap_lb_mm >= 1.2
    rep2 = Validator(geoms).validate([("battery_pack", 0, np.array([1.0, 1.0, 0.0]))], spec)
    assert not rep2.valid


def test_conservative_fuzz_no_false_accepts(geoms):
    """Random near-contact placements: every accepted pair must have true distance >= required - 1 µm."""
    import fcl
    from t2s.core.rotations import ROTATIONS_F
    rng = np.random.default_rng(7)
    names = sorted(geoms)
    v = Validator(geoms)
    accepted = rejected = 0
    for trial in range(250):
        a, b = rng.choice(names, 2, replace=False)
        ga, gb = geoms[a], geoms[b]
        oa = int(rng.choice(range(24)))
        ob = int(rng.choice(range(24)))
        direction = rng.normal(size=3)
        direction /= np.linalg.norm(direction)
        # bisect the translation along direction to near contact, then perturb by +-0.05 mm
        lo, hi = 0.0, 300.0
        oa_ = fcl.CollisionObject(ga.fcl_model(), fcl.Transform(ROTATIONS_F[oa], np.zeros(3)))
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            ob_ = fcl.CollisionObject(gb.fcl_model(), fcl.Transform(ROTATIONS_F[ob], direction * mid))
            if fcl.collide(oa_, ob_, fcl.CollisionRequest(), fcl.CollisionResult()):
                lo = mid
            else:
                hi = mid
        t = direction * (hi + rng.uniform(-0.05, 0.05))
        spec = StageSpec(1, np.full(3, -1e4), np.full(3, 1e4), 0.0, 0.0)
        rep = v.validate([(a, oa, np.zeros(3)), (b, ob, t)], spec)
        ob_ = fcl.CollisionObject(gb.fcl_model(), fcl.Transform(ROTATIONS_F[ob], t))
        collide = fcl.collide(oa_, ob_, fcl.CollisionRequest(), fcl.CollisionResult()) > 0
        if rep.valid:
            accepted += 1
            assert not collide, (a, b, oa, ob, t, rep.pairs[0])
            # containment cannot occur for these placements (b approached from outside)
        else:
            rejected += 1
    assert accepted > 20 and rejected > 20
