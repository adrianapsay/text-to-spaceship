"""M4: brackets that hold several parts — combined per wall and one piece (gd.multi, gd.simp, gd.multi_eval,
gd.layouts, proof.bracket_layout, tools/check_certificate.py check 10)."""
import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import DATA
from test_proof import CHECKER

from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import Validator
from t2s.constraints.stage2_model import Stage2Model
from t2s.gd import multi, multi_eval, simp
from t2s.gd.layouts import build_snapshot, combined_h, fits_build_volume, plan_combined
from t2s.proof.bracket_layout import certificate_brackets, spec_for_layout
from t2s.proof.certificate import build_certificate, proof_markdown

CURVED = ("pcb_obc", "pcb_eps", "ellipsoid_module", "l_shaped_electronics", "wedge_bracket", "sensor_housing_hex",
          "magnetometer_ring_torus", "gas_tank_capsule")


# ------------------------------------------------------------------------------------------------ synthetic parts
def box_part(lo, hi, mass):
    import manifold3d
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    m = manifold3d.Manifold.cube(list(hi - lo)).translate(list(lo))
    mesh = m.to_mesh()
    return SimpleNamespace(v=np.asarray(mesh.vert_properties)[:, :3].astype(float),
                           f=np.asarray(mesh.tri_verts).astype(np.int64), mass_kg=mass,
                           boxes=np.array([np.concatenate([lo, hi])]))


def am_bracket(pid, lo, hi, gap=3.0, axis=0, neg=True, plane=0.0, target="-x wall"):
    return {"name": f"bracket:{pid}", "pid": pid, "kind": "metal_am", "axis": axis, "neg": neg, "plane_mm": plane,
            "reserve": list(lo) + list(hi), "gap_mm": gap, "fasteners": 3, "target": target, "target_kind": "wall",
            "target_statics": [], "held_parts": [pid], "part_side_mm": gap, "depth_mm": 4.0}


@pytest.fixture(scope="module")
def pair():
    """Two box parts side by side 2.2 mm apart, each 3 mm from the wall x = 0, each with a metal-AM bracket."""
    recs = {"A": box_part([3, -18, -8], [23, -2, 8], 0.10), "B": box_part([3, 0.2, -8], [23, 16.2, 8], 0.12)}
    brs = [am_bracket("A", [0, -18, -8], [7, -2, 8]), am_bracket("B", [0, 0.2, -8], [7, 16.2, 8])]
    poses = {p: (0, np.zeros(3)) for p in recs}
    masses = {p: r.mass_kg for p, r in recs.items()}
    groups = multi.combine_groups(brs, {p: r.boxes for p, r in recs.items()}, [])
    return recs, brs, poses, masses, groups


def test_bridge_between_neighbours_and_its_clearance(pair):
    recs, brs, _, _, groups = pair
    assert len(groups) == 1 and groups[0]["pids"] == ["A", "B"]
    br = groups[0]["bridges"][0]
    assert br["gap_box"] == pytest.approx([0, -2, -8, 3, 0.2, 8])        # the gap, the shared width, the wall gap
    assert sorted(br["ends"]) == ["A", "B"]
    # a third part in the gap: no bridge (it must keep 1.2 mm from every part but its two ends)
    blocker = {"C": np.array([[4.0, -1.5, -20.0, 30.0, -0.3, -12.0]])}
    assert multi.combine_groups(brs, {**{p: r.boxes for p, r in recs.items()}, **blocker}, []) != []
    blocker = {"C": np.array([[0.5, -1.5, -4.0, 2.0, -0.3, 4.0]])}
    assert multi.combine_groups(brs, {**{p: r.boxes for p, r in recs.items()}, **blocker}, []) == []
    # a keep-out next to the gap blocks it; the target rail would not
    assert multi.combine_groups(brs, {p: r.boxes for p, r in recs.items()},
                                [("rod", "rod", np.array([0.0, -1.0, 9.0, 3.0, 0.0, 12.0]))]) == []
    # brackets on different walls are never joined
    other = am_bracket("B", [0, 0.2, -8], [7, 16.2, 8], plane=0.0, axis=0, neg=False)
    other["reserve"] = [-7, 0.2, -8, 0, 16.2, 8]
    assert multi.combine_groups([brs[0], other], {p: r.boxes for p, r in recs.items()}, []) == []


def test_combined_domain_regions(pair):
    recs, _, poses, masses, groups = pair
    dom = multi.combined_domain(groups[0], recs, poses, masses, 1.0)
    assert dom.kind == "combined" and len(dom.boxes) == 3 and dom.boxes[2]["role"] == "bridge"
    assert np.allclose(dom.boxes[2]["box"], [0, -3, -8, 3, 2, 8])          # one voxel into each member box
    for k, p in enumerate(dom.parts):
        assert p.contact.any() and p.fixed.any() and len(p.bolts) == 3
        assert np.all((dom.bits[p.contact] & (1 << k)) != 0)               # a part's contact only in its own box
        assert np.allclose(p.bolts[:, 0], 0.0)                              # bolts on the wall plane
    assert not (dom.fixed & dom.void).any() and not (dom.contact & dom.void).any()
    F = [dom.contact_voxel_forces(c) for c in dom.load_cases()]
    total = sum(p.mass_kg for p in dom.parts) * 68 * 9806.65e-3
    assert np.allclose([f.reshape(-1, 3).sum(0) for f in F], -total * np.eye(3))


def _bad_blocks(dom):
    bits = np.where(~dom.void, dom.bits, 0)
    P = np.pad(bits, 1)
    s = [n + 1 for n in bits.shape]
    common, nreg = np.full(s, -1, np.int64), np.zeros(s, int)
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                b = P[i:i + s[0], j:j + s[1], k:k + s[2]]
                common &= np.where(b != 0, b, -1)
                nreg += b != 0
    return int(((nreg >= 2) & (common == 0)).sum())


def test_corner_erosion_puts_every_block_in_one_box():
    """Offset footprints: the bridge meets each member box at re-entrant corners; after erosion the voxels of every
    2 × 2 × 2 block share a box, so every marching-cubes triangle lies in one certified box."""
    gap = 10.0
    recs = {"A": box_part([gap, -18, -8], [gap + 20, -2, 8], 0.15),
            "B": box_part([gap, 0.2, -4], [gap + 20, 16.2, 12], 0.2)}
    brs = [am_bracket("A", [0, -18, -8], [gap + 4, -2, 8], gap), am_bracket("B", [0, 0.2, -4], [gap + 4, 16.2, 12], gap)]
    groups = multi.combine_groups(brs, {p: r.boxes for p, r in recs.items()}, [])
    dom = multi.combined_domain(groups[0], recs, {p: (0, np.zeros(3)) for p in recs}, {"A": 0.15, "B": 0.2}, 1.0)
    assert "voxels removed at re-entrant corners" in dom.notes[0] and _bad_blocks(dom) == 0
    dens = np.where(dom.design(), 1.0, 0.0)                                # every design voxel solid
    sol, info = multi_eval.solid_from_density(dom, dens)
    assert sol is not None, info
    assert sum(info["triangles_per_box"].values()) == len(sol[1]) and multi_eval.closed_mesh(sol[1])


def test_surface_pulled_back_from_a_part_at_a_cut_corner():
    """An L of solid voxels around a void voxel that holds a part's corner: marching cubes cuts the voxel corner
    through the part; lowering the void corners of those cubes pulls the surface back into the solid voxels (no
    boolean, no slivers), the voxels keep their side and the surface stays closed."""
    d = np.zeros((4, 4, 3))
    d[:3, :3, :2] = 1.0
    d[2, 2, :] = 0.0
    part = box_part([2.1, 2.1, 0.2], [3.5, 3.5, 1.8], 0.1)
    dom = SimpleNamespace(h=np.ones(3), origin=np.zeros(3), parts=[SimpleNamespace(pid="P", v=part.v, f=part.f)])
    P = np.pad(d, 1)
    planes = [(2, 0.0)]
    v, f, good = multi_eval._surface(dom, P, planes)
    assert len(good) == 1 and multi_eval.closed_mesh(f)
    hit = multi_eval._part_hit_triangles(dom, v, f)
    assert len(hit) > 0                                                 # the cut corner reaches into the part
    rounds = 0
    while len(hit) and rounds < multi_eval.PULL_ROUNDS:
        assert multi_eval._pull_back(dom, P, v, f, hit) > 0
        v, f, good = multi_eval._surface(dom, P, planes)
        hit = multi_eval._part_hit_triangles(dom, v, f)
        rounds += 1
    assert len(hit) == 0 and 1 <= rounds < multi_eval.PULL_ROUNDS
    assert len(good) == 1 and multi_eval.closed_mesh(f)
    assert np.all((P[1:-1, 1:-1, 1:-1] >= 0.5) == (d >= 0.5))              # no voxel changed side
    dist = multi_eval.held_part_distances(dom, v, f)["P"]
    assert not dist["intersects"] and dist["distance_mm"] > 0.0


def test_load_path_rule_refuses_a_part_held_only_through_another(pair):
    recs, _, poses, masses, groups = pair
    dom = multi.combined_domain(groups[0], recs, poses, masses, 1.0)
    solid = dom.passive_solid()
    ok = multi.load_path(dom, solid)
    assert all(x["ok"] for x in ok.values())
    # B's own bolted layer and the bridge removed: its contact zone could reach the wall only through part A
    bad = copy.deepcopy(dom)
    a_bit, b_bit, br_bit = 1 << 0, 1 << 1, 1 << 2
    in_a = (bad.bits & a_bit) != 0
    cut = (((bad.bits & b_bit) != 0) & ~bad.parts[1].contact) | (((bad.bits & br_bit) != 0) & ~in_a)
    cut &= ~bad.parts[1].contact
    bad.void = bad.void | cut
    bad.fixed &= ~bad.void
    for p in bad.parts:
        p.fixed &= ~bad.void
        p.contact &= ~bad.void
    lp = multi.load_path(bad, bad.passive_solid())
    assert lp["A"]["ok"] and not lp["B"]["ok"] and lp["B"]["loose"] == lp["B"]["contact"]
    sol, info = multi_eval.solid_from_density(bad, np.zeros(bad.shape))
    assert sol is None and "never only by another part" in info["reason"] and "B:" in info["reason"]


def test_simp_fine_level_skipped_when_memory_is_short(pair):
    """mem_check refusing the fine level: the coarse level's densities on the fine grid are the design (passive solid
    1, nothing outside the active voxels, a fine design voxel in a coarse block that was passive or absent gets 0 —
    not its block's 1), and the levels say so. Without a coarse level (a grid under 8 voxels across) the MemoryError
    reaches the caller."""
    calls = []

    def short(ndof, what):
        calls.append((ndof, what))
        raise MemoryError("test: not enough memory")
    recs, _, poses, masses, groups = pair                                  # 7 voxels across: no coarse level
    dom = multi.combined_domain(groups[0], recs, poses, masses, 1.0)
    F = [dom.contact_voxel_forces(c) for c in dom.load_cases()]
    with pytest.raises(MemoryError):
        simp.solve(~dom.void, dom.passive_solid(), dom.fixed, F, dom.h, 0.33, 0.05, budget_s=30, threads=2,
                   mem_check=short)
    gap = 10.0                                                             # 14 voxels across: a coarse level
    recs = {"A": box_part([gap, -18, -8], [gap + 20, -2, 8], 0.15),
            "B": box_part([gap, 0.2, -4], [gap + 20, 16.2, 12], 0.2)}
    brs = [am_bracket("A", [0, -18, -8], [gap + 4, -2, 8], gap), am_bracket("B", [0, 0.2, -4], [gap + 4, 16.2, 12], gap)]
    groups = multi.combine_groups(brs, {p: r.boxes for p, r in recs.items()}, [])
    dom = multi.combined_domain(groups[0], recs, {p: (0, np.zeros(3)) for p in recs}, {"A": 0.15, "B": 0.2}, 1.0)
    F = [dom.contact_voxel_forces(c) for c in dom.load_cases()]
    active, solid = ~dom.void, dom.passive_solid()
    calls.clear()
    s = simp.solve(active, solid, dom.fixed, F, dom.h, 0.33, 0.05, budget_s=30, threads=2, mem_check=short)
    assert calls == [(int(3 * 1.15 * int(active.sum())), "SIMP")]
    assert [lv["level"] for lv in s["levels"]] == ["coarse", "fine"] and "memory" in s["levels"][1]["skipped"]
    rho = s["density"]
    assert rho.shape == active.shape and np.all(rho[~active] == 0.0) and np.all(rho[solid & active] == 1.0)
    assert rho.min() >= 0.0 and rho.max() <= 1.0
    design = active & ~solid
    print(f"\nmean density of the design voxels {rho[design].mean():.4f} (volume fraction 0.05)")
    assert rho[design].mean() < 0.15


def test_two_part_combined_design_checked_by_both_solvers(pair):
    """A small combined bracket: active-element SIMP, marching cubes in the certified boxes, NGSolve (one
    factorisation, 15 trial cases) and CalculiX (the three 68 g cases) agree; the parts' regions are scored."""
    from t2s.fea import ccx
    recs, _, poses, masses, groups = pair
    dom = multi.combined_domain(groups[0], recs, poses, masses, 1.0)
    F = [dom.contact_voxel_forces(c) for c in dom.load_cases()]
    s = simp.solve(~dom.void, dom.passive_solid(), dom.fixed, F, dom.h, 0.33, 0.05, budget_s=60, threads=2)
    ev = multi_eval.evaluate(dom, s["density"], threads=2)
    assert ev["ok"], ev.get("reason")
    assert ev["trial_cases"] == 6 * 2 + 3 and ev["n_nodes"] > 1000
    assert set(ev["parts_detail"]) == {"A", "B"} and all(x["ms_yield"] is not None for x in ev["parts_detail"].values())
    assert ev["f1_hz"] > 1000 and ev["modes"][0]["motion"].split()[0] in ("A", "B")
    assert sum(ev["triangles_per_box"].values()) == len(ev["mesh"][1])
    assert all(d is not None and d > 0 for d in ev["held_part_distance_mm"].values())
    if ccx.available():
        assert ev["agreement"]["disp_rel"] < 1e-4 and ev["agreement"]["sigma_rel"] < 1e-3
    assert ev["passed"], ev.get("reason")
    # its colour maps (multi_eval.display_fields): one value per surface vertex, the numbers of the whole bracket's
    # margins (every part loaded at once at the lightest one's quasi-static level)
    ids = {"util_body"} | {f"{p}_{a}" for p in ("vm_static", "vm_random_limit", "vm_random_qual", "disp_static")
                           for a in "xyz"}
    fields, info = ev["fields"], {f["id"]: f for f in ev["field_info"]["fields"]}
    assert set(fields) == ids and set(info) == ids
    assert all(len(x) == len(ev["mesh"][0]) and np.all(np.isfinite(x)) for x in fields.values())
    assert all(0 <= f["max"] <= f["max_all"] * (1 + 1e-6) for f in info.values())
    rows = {(r["case"], r["axis"]): r for r in ev["checks"]}
    for a in "xyz":
        for fid, case in (("vm_static", "static"), ("vm_random_limit", "random limit"),
                          ("vm_random_qual", "random qualification")):
            assert info[f"{fid}_{a}"]["max_all"] == pytest.approx(rows[(case, a)]["sigma_mpa"], rel=1e-6)
    body = [r for r in ev["checks"] if r["case"] in ("static", "random limit", "random qualification")]
    worst = min(min(r["ms_yield"], r["ms_ult"]) for r in body)
    assert info["util_body"]["max_all"] == pytest.approx(1.0 / (1.0 + worst), rel=1e-6)          # 1 = zero margin
    assert ev["field_info"]["solvers"] == list(ev["solvers"]) and len(ev["field_info"]["voxel_mm"]) == 3


# ------------------------------------------------------------------------------------------------ certificates
@pytest.fixture(scope="module")
def curved(dataset_parts):
    out = {}
    for n in CURVED:
        _, r = dataset_parts[n]
        c = copy.copy(r)
        c.id, c.tags = n, (["pcb"] if n.startswith("pcb") else [])
        out[n] = c
    return out


@pytest.fixture(scope="module")
def combined_layout(curved):
    """A budget-100 layout of curved parts with a combined bracket (the first of seed 3's decodes that has one)."""
    m = Stage2Model(curved, "default", am_level=3)
    rng = np.random.default_rng(3)
    for _ in range(300):
        k = rng.random(m.dim)
        r = m.decode(list(np.argsort(k[:m.n], kind="stable")), k[m.n:2 * m.n], k[2 * m.n:])
        if r.unplaced or r.meta["unmounted"] or r.meta["overflow_mm"] > 0:
            continue
        snap = build_snapshot("L-m4", curved, r.meta, r.poses, {p: 0.2 for p in curved}, "combined", "gevs",
                              "AlSi10Mg")
        groups = plan_combined(snap)
        if groups:
            return m, r, snap, groups
    pytest.fail("no layout with a combined bracket in 300 decodes")


def _check(cert, tmp_path):
    cp = tmp_path / "c.json"
    cp.write_text(json.dumps(cert))
    out = subprocess.run([sys.executable, "-I", str(CHECKER), str(cp), str(DATA)], capture_output=True, text=True,
                         timeout=900, check=False)
    return out.returncode, out.stdout


def _files(dataset_parts):
    return {n: (p["file"], p["sha256"]) for n, (p, _) in dataset_parts.items()}


@pytest.fixture(scope="module")
def combined_cert(combined_layout, curved, dataset_parts):
    m, r, snap, groups = combined_layout
    g = groups[0]
    dom = multi.combined_domain(g, snap["records"], snap["poses"], snap["masses"], combined_h(g))
    sol, info = multi_eval.solid_from_density(dom, np.where(dom.design(), 0.0, 0.0))
    assert sol is not None, info
    key = "+".join(sorted(g["pids"]))
    rec = {"name": g["name"], "parts": g["pids"], "boxes": [{**b, "box": np.asarray(b["box"]).tolist()}
                                                          for b in dom.boxes],
           "target": g["target"], "target_kind": g["target_kind"], "axis": g["axis"], "neg": g["neg"],
           "plane_mm": g["plane_mm"], "target_statics": g["target_statics"], "mass_kg": 0.01}
    layout = {"designs": {key: rec}}
    spec = spec_for_layout(m, r.meta, "combined", layout)
    rep = Validator({i: part_geom_from_record(x) for i, x in curved.items()}).validate(r.poses, spec, want_planes=True)
    assert rep.valid, rep.violations[:3]
    brs = certificate_brackets(r.meta, "combined", layout, lambda b: None, lambda d: sol)
    cert = build_certificate("L-m4", rep, curved, r.poses, spec, _files(dataset_parts), brackets=brs)
    return cert, rep, sol, rec


def test_combined_certificate_passes_the_checker(combined_cert, tmp_path):
    cert, rep, _, rec = combined_cert
    multi_entry = [b for b in cert["brackets"] if b.get("multi")]
    assert len(multi_entry) == 1 and multi_entry[0]["held_parts"] == rec["parts"]
    bridges = [b for b in multi_entry[0]["boxes"] if b["role"] == "bridge"]
    assert bridges and all(b["name"] in [it["name"] for it in cert["frame"]["items"]] for b in bridges)
    md = proof_markdown(cert, rep)
    assert "combined bracket" in md and "each inside one box" in md
    code, out = _check(cert, tmp_path)
    assert code == 0 and "OVERALL: PASS" in out, out
    for k in ("bracket_solids_in_boxes", "bracket_boxes_apart", "bracket_checks_complete", "exemptions_follow_rules",
              "brackets_fixed_to_chassis", "every_part_held"):
        assert f"PASS  {k}" in out, out


def test_combined_certificate_mutations(combined_cert, tmp_path):
    cert, _, _, _ = combined_cert

    def entry(c):
        return next(b for b in c["brackets"] if b.get("multi"))

    def expect(bad, key, text=""):
        code, out = _check(bad, tmp_path)
        assert code != 0 and f"FAIL  {key}" in out and text in out, out
    # a vertex moved out of every box (the triangles it belongs to leave the boxes)
    bad = copy.deepcopy(cert)
    b = entry(bad)
    ax = b["axis"]
    hi = max(x["box"][3 + ax] if b["neg"] else -x["box"][ax] for x in b["boxes"])
    v = b["solid_vertices"][0]
    v[ax] = (hi + 5.0) if b["neg"] else -(hi + 5.0)
    expect(bad, "bracket_solids_in_boxes", "lies in none of its boxes")
    # an open surface: one triangle dropped
    bad = copy.deepcopy(cert)
    entry(bad)["solid_faces"].pop()
    expect(bad, "bracket_solids_in_boxes", "not closed")
    # a bridge that is not a column on the target plane
    bad = copy.deepcopy(cert)
    b = entry(bad)
    br = next(x for x in b["boxes"] if x["role"] == "bridge")
    k = b["axis"] if b["neg"] else 3 + b["axis"]
    br["box"][k] += 0.5 if b["neg"] else -0.5
    expect(bad, "brackets_fixed_to_chassis", "does not start on its target plane")
    # a part exempt from a bridge it does not end on
    bad = copy.deepcopy(cert)
    b = entry(bad)
    br = next(x for x in b["boxes"] if x["role"] == "bridge")
    other = next(p for p in b["held_parts"] if p not in br["ends"]) if len(b["held_parts"]) > 2 else \
        next(p["id"] for p in bad["parts"] if p["id"] not in b["held_parts"])
    bad["exempt"].append([other, br["name"]])
    bad["statics"] = [s for s in bad["statics"] if not (s["part"] == other and s["static"] == br["name"])]
    expect(bad, "exemptions_follow_rules", "follows from no rule")
    # a bridge whose box-gap checks were dropped
    bad = copy.deepcopy(cert)
    b = entry(bad)
    br = next(x for x in b["boxes"] if x["role"] == "bridge")
    bad["static_pairs"] = [p for p in bad["static_pairs"] if br["name"] not in (p["a"], p["b"])]
    expect(bad, "bracket_checks_complete", "no box-gap check")
    # a bridge grown into a keep-out (corners changed everywhere it is used, so only the gap rule fails)
    bad = copy.deepcopy(cert)
    b = entry(bad)
    br = next(x for x in b["boxes"] if x["role"] == "bridge")
    pair = next(p for p in bad["static_pairs"] if br["name"] in (p["a"], p["b"]))
    other = pair["b"] if pair["a"] == br["name"] else pair["a"]
    oc = next(it for it in bad["frame"]["items"] if it["name"] == other)["corners"]
    olo = [min(p[i] for p in oc) for i in range(3)]
    ohi = [max(p[i] for p in oc) for i in range(3)]
    new = [min(br["box"][i], olo[i]) for i in range(3)] + [max(br["box"][3 + i], ohi[i]) for i in range(3)]
    br["box"] = new
    from t2s.constraints import stage2 as s2
    corners = s2.box_corners(np.array(new[:3]), np.array(new[3:])).tolist()
    for it in bad["frame"]["items"]:
        if it["name"] == br["name"]:
            it["corners"] = corners
    for s in bad["statics"]:
        if s["static"] == br["name"]:
            s["corners"] = corners
    for sp in bad["static_pairs"]:
        for kk in ("a", "b"):
            if sp[kk] == br["name"]:
                sp[f"corners_{kk}"] = corners
    expect(bad, "bracket_boxes_apart", "box gap")


def test_build_volume_rule():
    assert fits_build_volume([300.0, 80.0, 90.0]) and fits_build_volume([250.0, 250.0, 325.0])
    assert not fits_build_volume([330.0, 100.0, 100.0]) and not fits_build_volume([260.0, 260.0, 100.0])


@pytest.fixture(scope="module")
def one_piece_cert(combined_layout, curved, dataset_parts):
    """The one piece of the same layout, built from the passive voxels (pads, contact layers) joined into one piece
    (no optimisation, no FEA: the proof does not depend on them)."""
    m, r, _, _ = combined_layout
    snap = build_snapshot("L-m4", curved, r.meta, r.poses, {p: 0.2 for p in curved}, "one_piece", "gevs", "AlSi10Mg")
    dom = multi.one_piece_domain(snap["brackets"], snap["records"], snap["poses"], snap["masses"], snap["inner"],
                                 [(n, k, np.asarray(b)) for n, k, b in snap["keepouts"]],
                                 {p: np.asarray(b) for p, b in snap["nonheld_boxes"].items()})
    joined, joins = multi.join(dom, dom.passive_solid())
    sol, info = multi_eval.solid_from_density(dom, np.zeros(dom.shape), joined=joined)
    assert sol is not None, info
    rec = {"parts": [p.pid for p in dom.parts], "mass_kg": 0.01,
           "bolted": [{"part": p.pid, "axis": p.axis, "neg": p.neg, "plane_mm": p.plane, "footprint": p.box.tolist()}
                      for p in dom.parts], "held_part_distance_mm": info["held_part_distance_mm"]}
    layout = {"designs": {"one_piece": rec}}
    spec = spec_for_layout(m, r.meta, "one_piece", layout)
    rep = Validator({i: part_geom_from_record(x) for i, x in curved.items()}).validate(r.poses, spec, want_planes=True)
    assert rep.valid, rep.violations[:3]
    brs = certificate_brackets(r.meta, "one_piece", layout, lambda b: None, lambda d: sol)
    cert = build_certificate("L-m4", rep, curved, r.poses, spec, _files(dataset_parts), brackets=brs)
    return cert, rep, sol, dom, joins


def test_one_piece_certificate_passes_the_checker(one_piece_cert, tmp_path):
    cert, rep, _, dom, _ = one_piece_cert
    op = [b for b in cert["brackets"] if b.get("one_piece")]
    assert len(op) == 1 and set(op[0]["held_parts"]) == {p.pid for p in dom.parts}
    names = {it["name"] for it in cert["frame"]["items"]}
    assert not any(f"bracket:{p.pid}" in names for p in dom.parts)        # the boxes it replaces are gone
    md = proof_markdown(cert, rep)
    assert "one piece" in md and "numeric" in md
    code, out = _check(cert, tmp_path)
    assert code == 0 and "OVERALL: PASS" in out, out
    assert "PASS  one_piece_clear" in out and "PASS  every_part_held" in out and "numeric" in out


def test_one_piece_certificate_mutations(one_piece_cert, tmp_path):
    cert, _, _, _, _ = one_piece_cert

    def op(c):
        return next(b for b in c["brackets"] if b.get("one_piece"))

    def expect(bad, key, text=""):
        code, out = _check(bad, tmp_path)
        assert code != 0 and f"FAIL  {key}" in out and text in out, out
    # one vertex pulled into a PC/104 rod (its triangles cross the rod's 1.2 mm zone)
    bad = copy.deepcopy(cert)
    rod = next(it for it in bad["frame"]["items"] if it["kind"] == "rod")
    rlo = [min(p[i] for p in rod["corners"]) for i in range(3)]
    rhi = [max(p[i] for p in rod["corners"]) for i in range(3)]
    o = op(bad)
    o["solid_vertices"][0] = [(rlo[i] + rhi[i]) / 2 for i in range(3)]
    expect(bad, "one_piece_clear", "comes within")
    # an open surface
    bad = copy.deepcopy(cert)
    op(bad)["solid_faces"].pop()
    expect(bad, "one_piece_clear", "not closed")
    # bolted to a plane that is not a wall
    bad = copy.deepcopy(cert)
    bp = op(bad)["bolted"][0]
    bp["plane_mm"] += 5.0 if bp["neg"] else -5.0
    expect(bad, "one_piece_clear", "not a wall or end plate")
    # a part it does not hold claimed as held (the PC/104 board): exemption and holding without a rule
    bad = copy.deepcopy(cert)
    o = op(bad)
    o["held_parts"].append("pcb_obc")
    expect(bad, "every_part_held", "exempt parts")
