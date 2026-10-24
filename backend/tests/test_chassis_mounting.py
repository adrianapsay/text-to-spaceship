"""v2.5 chassis-only mounting: brackets are fixed to walls, end plates and corner rails only; the PC/104 stack hangs on
rods from its end plate; the fit certificate states the frame and the stand-alone checker proves the attachment
(Lemma 5). Layouts decoded before v2.5 keep their rules."""
import copy
import json
import subprocess
import sys

import numpy as np
import pytest
from conftest import DATA
from test_proof import CHECKER

from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import Validator
from t2s.constraints import stage2 as s2
from t2s.constraints.stage2_model import Stage2Model
from t2s.core.rotations import ROTATIONS_F
from t2s.mfg.brackets import cert_entry
from t2s.proof.certificate import build_certificate, proof_markdown

STACKED = ("pcb_obc", "pcb_eps", "battery_pack", "payload_electronics_box", "reaction_wheel", "magnetorquer_rod")
RODS = ("rod++", "rod+-", "rod-+", "rod--")


@pytest.fixture(scope="module")
def recs(dataset_parts):
    out = {}
    for n, (p, r) in dataset_parts.items():
        if p["role"] != "packable":
            continue
        c = copy.copy(r)
        c.id, c.tags = n, (["pcb"] if n.startswith("pcb") else [])
        out[n] = c
    return out


@pytest.fixture(scope="module")
def files(dataset_parts):
    return {n: (p["file"], p["sha256"]) for n, (p, r) in dataset_parts.items()}


def _decode(m, k):
    n = m.n
    return m.decode(list(np.argsort(k[:n], kind="stable")), k[n:2 * n], k[2 * n:])


def test_no_bracket_lands_on_the_pc104_stack(recs):
    """The decoder gets no target but the corner rails, and neither the V2 bracket check nor the V1 Manufacturable
    tab offers the stack as a target."""
    m = Stage2Model(recs, "default")
    seen = []
    rng = np.random.default_rng(21)
    r = _decode(m, rng.random(m.dim))
    dec = m.decoders["default-stack"]
    plain_decode = dec.decode

    def spy(*a, **kw):
        seen.append(list(kw.get("extra_targets") or []))
        return plain_decode(*a, **kw)
    dec.decode = spy
    kinds = set()
    for _ in range(12):
        r = _decode(m, rng.random(m.dim))
        for b in r.meta["brackets"]:
            kinds.add(b["target_kind"])
            assert "PC/104" not in b["target"] and b["held_parts"] == [b["pid"]] and "target_parts" not in b
            assert all(t.startswith("rail") for t in b["target_statics"])
    assert seen and not any(any(t) for t in seen)                # harness breaks, rods, stack: never a target
    spec = m._mount_spec(len(m._statics_rails))
    assert spec.targets == [True] * len(m._statics_rails)        # the corner rails, nothing else
    assert kinds <= {"wall", "end_plate", "rail"}
    v1 = Stage2Model(recs, "default", mfg=True)
    for _ in range(6):
        r = _decode(v1, rng.random(v1.dim))
        assert not any("PC/104" in str(v.get("target", "")) for v in r.meta["mounts"].values())


def _stacked_layout(m, seed=4, tries=300):
    rng = np.random.default_rng(seed)
    for _ in range(tries):
        r = _decode(m, rng.random(m.dim))
        if not r.unplaced and not r.meta["unmounted"] and r.meta["overflow_mm"] <= 0 and r.meta.get("rod_end"):
            return r
    return None


@pytest.fixture(scope="module")
def stacked(recs, files):
    """A fully mounted default-mode layout with the PC/104 stack, its certificate and the checker's verdict."""
    sub = {k: recs[k] for k in STACKED}
    m = Stage2Model(sub, "default")
    r = _stacked_layout(m)
    assert r is not None, "no fully mounted stacked layout in 300 random decodes"
    spec = m.spec(r.meta)
    rep = Validator({i: part_geom_from_record(x) for i, x in sub.items()}).validate(r.poses, spec, want_planes=True)
    assert rep.valid, rep.violations[:3]
    cert = build_certificate("L-ws1", rep, sub, r.poses, spec, files, brackets=[cert_entry(b) for b in r.meta["brackets"]])
    return m, r, rep, cert


def _check(cert, tmp_path):
    cp = tmp_path / "c.json"
    cp.write_text(json.dumps(cert))
    out = subprocess.run([sys.executable, "-I", str(CHECKER), str(cp), str(DATA)], capture_output=True, text=True,
                         timeout=600, check=False)
    return out.returncode, out.stdout


def _set_corners(cert, name, corners):
    """Change one frame item's corners everywhere it is used (so only the rule about it can fail)."""
    for it in cert["frame"]["items"]:
        if it["name"] == name:
            it["corners"] = corners
    for s in cert["statics"]:
        if s["static"] == name:
            s["corners"] = corners
    for sp in cert["static_pairs"]:
        for k in ("a", "b"):
            if sp[k] == name:
                sp[f"corners_{k}"] = corners


def test_certificate_proves_chassis_mounting(stacked, tmp_path):
    _, r, rep, cert = stacked
    fr = cert["frame"]
    assert cert["certificate_version"] == 2 and fr["rules"] == "v2.5" and fr["rod_end"] == r.meta["rod_end"]
    assert sorted(fr["stack_ids"]) == ["pcb_eps", "pcb_obc"]
    assert {it["kind"] for it in fr["items"]} >= {"rail", "rod", "stack", "harness", "bracket"}
    lo, hi = s2.inner_box()
    assert fr["planes_mm"]["z"] == pytest.approx([lo[2], hi[2]])
    assert all(b["target_kind"] in ("wall", "end_plate", "rail") and b["exempt_parts"] == b["held_parts"]
               for b in cert["brackets"])
    md = proof_markdown(cert, rep)
    assert "Lemma 5" in md and "PC/104 deck" not in md
    code, out = _check(cert, tmp_path)
    assert code == 0 and "OVERALL: PASS" in out, out
    for k in ("frame_items_complete", "exemptions_follow_rules", "brackets_fixed_to_chassis", "every_part_held",
              "stack_rods_to_end_plate"):
        assert f"PASS  {k}" in out, out


def test_checker_mutations(stacked, tmp_path):
    """Each tampering is caught by the rule it breaks."""
    _, r, _, cert = stacked

    def expect(bad, key, text=""):
        code, out = _check(bad, tmp_path)
        assert code != 0 and f"FAIL  {key}" in out and text in out, out

    i = 0
    # a bracket fixed to a part: on the PC/104 deck, touching the stack reserve, the boards exempt from it
    bad = copy.deepcopy(cert)
    b = bad["brackets"][i]
    b["target_kind"], b["target_statics"] = "deck", ["stack_reserve"]
    expect(bad, "brackets_fixed_to_chassis", "not to the chassis")
    bad["exempt"].append(["pcb_obc", b["name"]])
    expect(bad, "exemptions_follow_rules", "follows from no rule")
    # a bracket claiming a target plane inside the enclosure
    bad = copy.deepcopy(cert)
    b = bad["brackets"][i]
    b["plane_mm"] += 1.0 if b["neg"] else -1.0
    expect(bad, "brackets_fixed_to_chassis")
    # a part without a bracket: the bracket, its box and every check of it removed
    bad = copy.deepcopy(cert)
    b = bad["brackets"].pop(i)
    bad["frame"]["items"] = [it for it in bad["frame"]["items"] if it["name"] != b["name"]]
    bad["statics"] = [s for s in bad["statics"] if s["static"] != b["name"]]
    bad["static_pairs"] = [p for p in bad["static_pairs"] if b["name"] not in (p["a"], p["b"])]
    bad["exempt"] = [e for e in bad["exempt"] if e[1] != b["name"]]
    expect(bad, "every_part_held", "held by no bracket")
    # exempt parts other than the held part
    bad = copy.deepcopy(cert)
    bad["brackets"][i]["exempt_parts"].append("pcb_eps")
    expect(bad, "every_part_held", "are not its held parts")
    # a bracket allowed to touch a rod
    bad = copy.deepcopy(cert)
    bad["brackets"][i]["target_statics"].append("rod++")
    expect(bad, "brackets_fixed_to_chassis", "only a corner rail may be touched")
    # a part exempt from a rod
    bad = copy.deepcopy(cert)
    bad["exempt"].append([bad["brackets"][i]["part"], "rod++"])
    expect(bad, "exemptions_follow_rules")
    # rods ending short of the end plate
    bad = copy.deepcopy(cert)
    rod = next(it for it in bad["frame"]["items"] if it["name"] == "rod++")
    z = 0 if r.meta["rod_end"] == "-z" else 1
    end = min(p[2] for p in rod["corners"]) if z == 0 else max(p[2] for p in rod["corners"])
    _set_corners(bad, "rod++", [[p[0], p[1], p[2] + (1.0 if z == 0 else -1.0) if p[2] == end else p[2]]
                                for p in rod["corners"]])
    expect(bad, "stack_rods_to_end_plate", "ends short")
    # a moved rail
    bad = copy.deepcopy(cert)
    rail = next(it for it in bad["frame"]["items"] if it["kind"] == "rail")
    sx = 1.0 if min(p[0] for p in rail["corners"]) < 0 else -1.0       # inwards
    _set_corners(bad, rail["name"], [[p[0] + 3.0 * sx, p[1], p[2]] for p in rail["corners"]])
    expect(bad, "frame_items_complete", "not in a corner")
    # inconsistent corners: a frame item's box differs in one clearance check
    bad = copy.deepcopy(cert)
    s = next(s for s in bad["statics"] if s["static"].startswith("rail") and s["method"] != "numeric")
    s["corners"] = [[p[0], p[1], p[2] * 0.5] for p in s["corners"]]
    expect(bad, "frame_items_complete", "corners differ")
    # a solid off its plane: its face on the target plane moved 0.5 mm into the box
    bad = copy.deepcopy(cert)
    j = next(k for k, b in enumerate(bad["brackets"]) if b["solid_vertices"])
    b = bad["brackets"][j]
    ax, plane = b["axis"], b["plane_mm"]
    step = 0.5 if b["neg"] else -0.5
    for v in b["solid_vertices"]:
        if abs(v[ax] - plane) < 1e-6:
            v[ax] += step
    expect(bad, "brackets_fixed_to_chassis", "does not touch its target plane")
    # the frame block dropped from a version-2 Stage 2 certificate
    bad = copy.deepcopy(cert)
    bad["frame"] = None
    expect(bad, "frame_items_complete", "without its frame block")


def _legacy_deck_layout(recs):
    """A layout as the rules before v2.5 made it: the stack anywhere with rods over its span only, and a machined
    block from a part's mounting side down to the PC/104 deck (the stack's top)."""
    sub = {k: recs[k] for k in ("pcb_obc", "pcb_eps", "payload_electronics_box")}
    m = Stage2Model(sub, "default")
    poses, block, span = m.stack_layout(0.0)
    pid = "payload_electronics_box"
    _, a, sgn = m.pads[pid]
    o = next(o for o in range(24) if (sgn * ROTATIONS_F[o][:, a])[2] < -0.5 and m._rep(pid, o) in m.allowed[pid])
    b = sub[pid].orient_bounds[o]
    gap = 6.0
    side = block[5] + gap
    t = np.round(np.array([-(b[0] + b[3]) / 2, -(b[1] + b[4]) / 2, side - b[2]]) * 1000) / 1000
    lo, hi = b[:3] + t, b[3:] + t
    c, w = 0.5 * (lo + hi), 0.3 * (hi - lo)
    reserve = [c[0] - w[0], c[1] - w[1], float(block[5]), c[0] + w[0], c[1] + w[1], float(side)]
    bracket = {"name": f"bracket:{pid}", "pid": pid, "kind": "machined", "mount_type": "machined spacer block",
               "process": "machined", "fasteners": 4, "gap_mm": gap, "target": "PC/104 stack top",
               "target_statics": ["stack_reserve", *RODS], "target_parts": list(m.pcb), "reserve": reserve,
               "axis": 2, "neg": True, "part_side_mm": float(side), "plane_mm": float(block[5]), "depth_mm": 0.0}
    meta = {"mode": "default", "stack_z": span[0], "stack_span": span, "stack_block": block.tolist(),
            "stack_ids": list(m.pcb), "rod_xy": m.rod_xy, "brackets": [bracket], "overflow_mm": 0.0}
    return sub, m, poses + [(pid, m._rep(pid, o), t)], meta


def test_a_legacy_layout_keeps_its_rules_and_its_proof(recs, files, tmp_path):
    sub, m, poses, meta = _legacy_deck_layout(recs)
    geoms = {i: part_geom_from_record(x) for i, x in sub.items()}
    spec = m.spec(meta)
    rods = {s.name: s.corners for s in spec.statics if s.kind == "rod"}
    span = meta["stack_span"]
    for c in rods.values():                                    # rods over the stack span only, as decoded then
        assert (c[:, 2].min(), c[:, 2].max()) == pytest.approx(span) and np.ptp(c[:, 0]) == pytest.approx(s2.ROD_D)
    rep = Validator(geoms).validate(poses, spec, want_planes=True)
    assert rep.valid, rep.violations[:3]
    cert = build_certificate("L-old", rep, sub, poses, spec, files, brackets=[cert_entry(b) for b in meta["brackets"]])
    assert cert["frame"]["rules"] == "legacy" and cert["brackets"][0]["target_kind"] == "deck"
    assert sorted(cert["brackets"][0]["exempt_parts"]) == sorted(["payload_electronics_box", *m.pcb])
    code, out = _check(cert, tmp_path)
    assert code == 0 and "OVERALL: PASS" in out and "before v2.5" in out, out
    # an issued version-1 certificate (no frame block, no attachment fields) still verifies
    old = copy.deepcopy(cert)
    old["certificate_version"] = 1
    del old["frame"]
    for b in old["brackets"]:
        for k in ("target_kind", "axis", "neg", "plane_mm", "held_parts"):
            b.pop(k)
    code, out = _check(old, tmp_path)
    assert code == 0 and "OVERALL: PASS" in out and "version 1" in out, out
    # the same layout under the v2.5 rules: the deck bracket touches the stack, which is not allowed any more
    rep = Validator(geoms).validate(poses, m.spec(dict(meta, rod_model="v2.5-end-plate")), want_planes=False)
    assert not rep.valid and any("stack_reserve" in v or "pcb_" in v for v in rep.violations)
