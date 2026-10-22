"""M3: box decoder feasibility, known optima, slab post-optimiser, bounds (protocol tests T-O)."""
import numpy as np
import pytest

from t2s.collision.geom import part_geom_from_record, to_world
from t2s.collision.validate import StageSpec, Validator
from t2s.decoders.box_decoder import PLACEMENT_GAP_STAGE1, BoxDecoder, ProxyPart
from t2s.geometry.stl_io import write_binary_stl
from t2s.objectives.metrics import ENCLOSURE_HI, ENCLOSURE_LO, layout_metrics
from t2s.optimise.bounds import lower_bounds
from t2s.optimise.slabs import slab_candidates
from t2s.parts.build import build_part

STAGE1 = StageSpec(1, ENCLOSURE_LO, ENCLOSURE_HI, 0.0, 0.0)


def box_part(tmp_path, dims, pid):
    x, y, z = dims
    v = np.array([[0, 0, 0], [x, 0, 0], [x, y, 0], [0, y, 0], [0, 0, z], [x, 0, z], [x, y, z], [0, y, z]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    p = tmp_path / f"{pid}.stl"
    write_binary_stl(p, v, f)
    return build_part(p.read_bytes(), pid, pid)


def decoder_for(recs):
    return BoxDecoder([ProxyPart(r.id, r.boxes, r.allowed_orients) for r in recs], ENCLOSURE_LO, ENCLOSURE_HI,
                      PLACEMENT_GAP_STAGE1)


PROXY_EPS = 2e-6      # certified boxes are inflated by 1 µm on each side


@pytest.mark.parametrize("dims,count,layers,expected", [((49.99, 49.99, 49.99), 8, 2, 99.98), ((90, 90, 1.6), 4, 4, 6.4)])
def test_known_optima_best_fit(tmp_path, dims, count, layers, expected):
    """Widths leave room for the 5 µm placement gap (two 50 mm boxes need 100.005 mm in a 100 mm section)."""
    recs = [box_part(tmp_path, dims, f"b{i}") for i in range(count)]
    res = decoder_for(recs).best_fit_all_orientations(list(range(count)))
    assert not res.unplaced
    assert res.length_top <= expected + layers * (PLACEMENT_GAP_STAGE1 + PROXY_EPS) + 1e-5   # float32 ulp at 50 mm
    geoms = {r.id: part_geom_from_record(r) for r in recs}
    assert Validator(geoms).validate(res.poses, STAGE1).valid


def test_known_optimum_with_orientation_genes(tmp_path):
    """16 boxes 50x50x85 fill 340 mm only when all stand upright: greedy best-fit lays them flat, so the
    optimum is reached through the decoder's orientation genes (which the genetic search evolves)."""
    recs = [box_part(tmp_path, (49.99, 49.99, 85), f"b{i}") for i in range(16)]
    dec = decoder_for(recs)
    keys = []
    for r in recs:
        upright = [k for k in r.allowed_orients if abs((r.orient_bounds[k, 5] - r.orient_bounds[k, 2]) - 85) < 1e-6]
        keys.append((r.allowed_orients.index(upright[0]) + 0.5) / len(r.allowed_orients))
    res = dec.decode(list(range(16)), np.array(keys), np.zeros(16))
    assert not res.unplaced
    assert res.length_top <= 340.0 + 4 * (PLACEMENT_GAP_STAGE1 + PROXY_EPS) + 1e-6
    geoms = {r.id: part_geom_from_record(r) for r in recs}
    assert Validator(geoms).validate(res.poses, STAGE1).valid


@pytest.fixture(scope="module")
def dataset_setup(dataset_parts):
    recs = [r for n, (p, r) in dataset_parts.items() if p["role"] == "packable"]
    geoms = {r.id: part_geom_from_record(r) for r in recs}
    return recs, geoms, decoder_for(recs), {r.id: r for r in recs}


def test_random_chromosomes_always_valid(dataset_setup):
    recs, geoms, dec, by_id = dataset_setup
    rng = np.random.default_rng(3)
    n = len(recs)
    val = Validator(geoms)
    for _ in range(25):
        k = rng.random(3 * n)
        res = dec.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
        rep = val.validate(res.poses, STAGE1)
        assert rep.valid, rep.violations


def test_decoder_is_deterministic(dataset_setup):
    recs, geoms, dec, _ = dataset_setup
    n = len(recs)
    k = np.random.default_rng(11).random(3 * n)
    a = dec.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
    b = dec.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])
    assert [p[0] for p in a.poses] == [p[0] for p in b.poses]
    assert all(pa[1] == pb[1] and np.array_equal(pa[2], pb[2]) for pa, pb in zip(a.poses, b.poses))


def test_slab_postoptimiser_keeps_length_and_validity(dataset_setup):
    recs, geoms, dec, by_id = dataset_setup
    order = list(np.argsort([-r.volume_mm3 for r in recs]))
    res = dec.best_fit_all_orientations(order)
    zint = []
    for pid, o, t in res.poses:
        hw = to_world(geoms[pid].hull_pts, o, t)
        zint.append((hw[:, 2].min(), hw[:, 2].max()))
    base = layout_metrics(by_id, geoms, res.poses)
    val = Validator(geoms)
    checked = 0
    for cand in slab_candidates(res.poses, zint, rng=np.random.default_rng(0)):
        m = layout_metrics(by_id, geoms, cand)
        assert abs(m["length_used_mm"] - base["length_used_mm"]) < 1e-6
        if checked < 6:
            assert val.validate(cand, STAGE1).valid
            checked += 1
    assert checked > 0


def test_lower_bounds_on_dataset(dataset_setup):
    recs, _, _, _ = dataset_setup
    b = {x["name"]: x for x in lower_bounds(recs)}
    assert abs(b["solid volume"]["value_mm"] - 108.0) < 0.1
    assert abs(b["largest smallest-dimension"]["value_mm"] - 59.9) < 0.2
    assert b["solid volume"]["valid_for"] == "true geometry"
    assert b["compound-box volume"]["valid_for"] == "box proxies only"
