"""Fit proof: certificate + stand-alone checker round trip, and mutation tests (Addendum 3.2b)."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from conftest import DATA
from t2s.collision.geom import part_geom_from_record
from t2s.collision.validate import StageSpec, Validator
from t2s.constraints.stage2 import Stage2Config, stage2_spec
from t2s.proof.certificate import build_certificate, proof_markdown

CHECKER = Path(__file__).resolve().parents[2] / "tools" / "check_certificate.py"
STAGE1 = StageSpec(1, np.array([-50.0, -50.0, -170.25]), np.array([50.0, 50.0, 170.25]), 0.0, 0.0)


def column_layout(dataset_parts, names, gap, start=-165.0, pick=None):
    """Stack parts along Z (flattest orientation each), centred in XY, with a face gap."""
    poses, z = [], start
    for name in names:
        rec = dataset_parts[name][1]
        if pick and name in pick:
            o = pick[name]
        else:
            o = min(rec.allowed_orients, key=lambda k: rec.orient_bounds[k, 5] - rec.orient_bounds[k, 2])
        b = rec.orient_bounds[o]
        t = np.array([-(b[0] + b[3]) / 2, -(b[1] + b[4]) / 2, z - b[2]])
        poses.append((name, o, t))
        z = t[2] + b[5] + gap
    return poses


@pytest.fixture(scope="module")
def setup(dataset_parts):
    geoms = {n: part_geom_from_record(r) for n, (p, r) in dataset_parts.items() if r.volume_mm3}
    records = {n: r for n, (p, r) in dataset_parts.items()}
    files = {n: (p["file"], p["sha256"]) for n, (p, r) in dataset_parts.items()}
    return geoms, records, files


def run_checker(cert, tmp_path):
    cp = tmp_path / "certificate.json"
    cp.write_text(json.dumps(cert))
    out = subprocess.run([sys.executable, "-I", str(CHECKER), str(cp), str(DATA)], capture_output=True, text=True,
                         timeout=600)
    return out.returncode, out.stdout


def test_round_trip_stage1(setup, dataset_parts, tmp_path):
    geoms, records, files = setup
    names = ["battery_pack", "pcb_obc", "l_shaped_electronics", "magnetometer_ring_torus", "irregular_blob",
             "fixture_flipped_normals"]
    poses = column_layout(dataset_parts, names, gap=0.5)
    rep = Validator(geoms).validate(poses, STAGE1)
    assert rep.valid, rep.violations
    cert = build_certificate("L-test", rep, records, poses, STAGE1, files)
    md = proof_markdown(cert, rep, {"com_mm": [0, 0, 0]})
    assert "Lemma 1" in md and "Theorem" in md
    code, out = run_checker(cert, tmp_path)
    assert code == 0, out
    assert "OVERALL: PASS" in out


def test_rod_through_torus_certificate(setup, dataset_parts, tmp_path):
    geoms, records, files = setup
    tor = records["magnetometer_ring_torus"]
    rod = records["magnetorquer_rod"]
    ot = int(np.argmin(tor.orient_bounds[:, 5] - tor.orient_bounds[:, 2]))
    orr = int(np.argmax(rod.orient_bounds[:, 5] - rod.orient_bounds[:, 2]))
    poses = [("magnetometer_ring_torus", ot, np.zeros(3)), ("magnetorquer_rod", orr, np.zeros(3))]
    rep = Validator(geoms).validate(poses, STAGE1)
    assert rep.valid and rep.pairs[0].level == "G3"
    cert = build_certificate("L-nest", rep, records, poses, STAGE1, files)
    code, out = run_checker(cert, tmp_path)
    assert code == 0, out


def test_mutation_moved_part_fails(setup, dataset_parts, tmp_path):
    geoms, records, files = setup
    poses = column_layout(dataset_parts, ["battery_pack", "payload_electronics_box"], gap=1.0)
    rep = Validator(geoms).validate(poses, STAGE1)
    cert = build_certificate("L-m", rep, records, poses, STAGE1, files)
    bad = copy.deepcopy(cert)
    bad["parts"][1]["t_mm"][2] -= 2.0            # pushes the box 1 mm into the battery
    code, out = run_checker(bad, tmp_path)
    assert code != 0 and "FAIL" in out


def test_mutation_corrupted_plane_fails(setup, dataset_parts, tmp_path):
    geoms, records, files = setup
    poses = column_layout(dataset_parts, ["battery_pack", "payload_electronics_box"], gap=1.0)
    rep = Validator(geoms).validate(poses, STAGE1)
    cert = build_certificate("L-m2", rep, records, poses, STAGE1, files)
    bad = copy.deepcopy(cert)
    bad["pairs"][0]["n"] = [1.0, 0.0, 0.0]
    bad["pairs"][0]["method"] = "hull_plane"
    code, out = run_checker(bad, tmp_path)
    assert code != 0


def test_scaled_parts_round_trip_and_tampered_scale_fails(setup, dataset_parts, tmp_path):
    """V2 part-size slider: a layout of parts at 70 % is certified at that size, and the checker rebuilds them at
    it; claiming a larger size than the layout was checked at fails."""
    from t2s.parts.scale import scale_part
    _, records, files = setup
    names = ["battery_pack", "magnetometer_ring_torus", "irregular_blob", "pcb_obc"]
    small = {n: scale_part(records[n], 0.7) for n in names}
    geoms = {n: part_geom_from_record(r) for n, r in small.items()}
    poses, z = [], -165.0
    for n in names:                                 # stacked with a 0.3 mm gap at the scaled size
        r = small[n]
        o = min(r.allowed_orients, key=lambda k: r.orient_bounds[k, 5] - r.orient_bounds[k, 2])
        b = r.orient_bounds[o]
        poses.append((n, o, np.array([-(b[0] + b[3]) / 2, -(b[1] + b[4]) / 2, z - b[2]])))
        z = poses[-1][2][2] + b[5] + 0.3
    rep = Validator(geoms).validate(poses, STAGE1)
    assert rep.valid, rep.violations
    cert = build_certificate("L-scaled", rep, small, poses, STAGE1, files)
    assert all(p["part_scale"] == pytest.approx(0.7) for p in cert["parts"])
    code, out = run_checker(cert, tmp_path)
    assert code == 0 and "OVERALL: PASS" in out, out
    bad = copy.deepcopy(cert)
    for p in bad["parts"]:
        p["part_scale"] = 0.8                       # bigger parts than were certified: they overlap
    code, out = run_checker(bad, tmp_path)
    assert code != 0 and "FAIL" in out


def test_stage2_spec_frame(setup, dataset_parts):
    from t2s.constraints.stage2 import frame_mass_props
    m, c, i = frame_mass_props()
    assert 0.7 < m < 1.0                           # ~0.876 kg (cross-check arithmetic)
    assert np.allclose(c, 0, atol=1e-9)
    spec = stage2_spec(Stage2Config(pcb_ids=["pcb_obc"], stack_z=(-150.0, -130.0)))
    kinds = sorted({s.kind for s in spec.statics})
    assert kinds == ["harness", "rail", "rod"]
    # harness interrupted across the PCB stack: two segments
    assert len([s for s in spec.statics if s.kind == "harness"]) == 2
