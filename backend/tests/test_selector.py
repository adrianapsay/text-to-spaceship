"""M6: algorithm selector default rules, sweeps, maps; height-map decoder soundness; LAHC/LS smoke."""
import numpy as np
import pytest

from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import StageSpec, Validator
from t2s.decoders.heightmap import HeightmapDecoder
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO
from t2s.optimise.selector import PartStats, grid_map, select_algorithm, sweep

CURVY = PartStats(19, 1.08e6, 0.40, {"curved": 0.4})
BOXY = PartStats(10, 1.0e6, 0.05, {"box-like": 0.9})
S = {"space": 25, "balance": 25, "inertia": 25, "feasibility": 25, "mass_symmetry": 50, "cable": 0, "cost": 0}


def test_default_rules():
    assert select_algorithm(1, {**S, "space": 70, "balance": 10, "inertia": 10}, CURVY).id == "hybrid_heightmap"
    assert select_algorithm(1, {**S, "space": 70, "balance": 10, "inertia": 10}, BOXY).id == "portfolio"
    assert select_algorithm(1, {**S, "space": 10, "balance": 70, "inertia": 10}, CURVY).id == "hybrid_box"
    assert select_algorithm(1, S, CURVY).id == "portfolio"
    c = select_algorithm(2, {**S, "space": 90}, CURVY)
    assert c.id == "hybrid_box" and "Stage 2" in c.reasons[0]
    for ch in (select_algorithm(1, S, CURVY), c):
        assert "default rule — no benchmark evidence yet" in ch.reasons[0] and ch.rule == "default"


def test_sweep_and_map_are_deterministic_and_consistent():
    sw = sweep(1, S, CURVY, "space")
    assert sw["values"] == list(range(101)) and len(sw["choices"]) == 101
    assert sw == sweep(1, S, CURVY, "space")
    for v, ch in zip(sw["values"], sw["choices"]):
        assert ch == select_algorithm(1, {**S, "space": v}, CURVY).id
    # the switch points are where the packing weight crosses the documented thresholds
    assert sw["choices"][0] == "hybrid_box" and sw["choices"][100] == "hybrid_heightmap"
    m = grid_map(1, S, CURVY, "space", "balance", n=11)
    assert len(m["grid"]) == 11 and all(len(r) == 11 for r in m["grid"])
    assert m["grid"][0][10] == select_algorithm(1, {**S, "space": 100, "balance": 0}, CURVY).id


def test_evidence_overrides_default_rule():
    ev = [{"stage": 1, "algorithm": "hybrid_box", "weights": {"L": 0.25, "D": 0.25, "I": 0.25}, "median_g": 0.30, "n": 10},
          {"stage": 1, "algorithm": "hybrid_heightmap", "weights": {"L": 0.25, "D": 0.25, "I": 0.25}, "median_g": 0.20,
           "n": 10}]
    c = select_algorithm(1, S, BOXY, evidence=ev)
    assert c.id == "hybrid_heightmap" and c.rule == "evidence"


@pytest.fixture(scope="module")
def recs(dataset_parts):
    return {r.id: r for n, (p, r) in dataset_parts.items() if p["role"] == "packable"}


@pytest.mark.parametrize("h", [2.0, 1.0])
def test_heightmap_layouts_always_validate(recs, h):
    ids = list(recs)
    dec = HeightmapDecoder({i: (recs[i].v, recs[i].f, recs[i].allowed_orients) for i in ids}, ENCLOSURE_LO,
                           ENCLOSURE_HI, h=h)
    val = Validator({i: part_geom_from_record(recs[i]) for i in ids})
    spec = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)
    rng = np.random.default_rng(int(h * 10))
    n = len(ids)
    for _ in range(8 if h == 2.0 else 3):
        k = rng.random(3 * n)
        r = dec.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
        rep = val.validate(r.poses, spec)
        assert rep.valid, rep.violations
        assert all(np.allclose(t * 1000, np.round(t * 1000), atol=1e-6) for _, _, t in r.poses)   # integer µm
    order = list(np.argsort([-recs[i].obb_extents_mm.min() for i in ids]))
    r = dec.best_fit_all_orientations(order)
    assert not r.unplaced and val.validate(r.poses, spec).valid


def test_heightmap_uses_open_bores():
    """A rod dropped onto an upright tube's open bore goes inside it (2.5-D columns see the hole)."""
    import trimesh
    tube = trimesh.creation.annulus(r_min=10, r_max=14, height=40)
    rod = trimesh.creation.cylinder(radius=4, height=30)
    parts = {"tube": (np.asarray(tube.vertices), np.asarray(tube.faces), [0]),
             "rod": (np.asarray(rod.vertices), np.asarray(rod.faces), [0])}
    dec = HeightmapDecoder(parts, np.array([-20.0, -20.0, 0.0]), np.array([20.0, 20.0, 100.0]), h=1.0)
    r = dec.decode([0, 1], np.zeros(2), np.ones(2))             # rule 1: toward the axis
    top = {pid: t[2] for pid, _, t in r.poses}
    assert not r.unplaced
    assert top["rod"] < 40.0, top          # the rod's centre sits below the tube's top: it is inside the bore
