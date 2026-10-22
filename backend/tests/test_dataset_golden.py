"""M1 golden dataset tests: hashes, analytic mass properties, fixtures, proxies (protocol T-G, T-M, T-C proxy)."""
import hashlib

import numpy as np
import pytest

from conftest import DATA


def test_manifest_hashes(manifest):
    joined = []
    for p in manifest["parts"]:
        data = (DATA / p["file"]).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        assert sha == p["sha256"], p["file"]
        joined.append(f"{p['file']}:{sha}")
    assert hashlib.sha256("\n".join(sorted(joined)).encode()).hexdigest() == manifest["dataset_sha256"]


def _analytic_in_canonical(p, rec):
    a = p["analytic"]
    r, o = rec.r_auth_to_can, rec.origin_auth
    return a["volume_mm3"], (np.array(a["com_mm"]) - o) @ r, r.T @ np.array(a["inertia_about_com_unit_density_mm5"]) @ r


@pytest.mark.parametrize("name", [
    "battery_pack", "l_shaped_electronics", "u_channel_bracket", "cross_connector_hub", "fixture_two_bodies"])
def test_exact_representable_parts_match_to_1e12(dataset_parts, name):
    p, rec = dataset_parts[name]
    vol, com, j = _analytic_in_canonical(p, rec)
    assert abs(rec.volume_mm3 - vol) / vol < 1e-12
    assert np.linalg.norm(rec.com_can_mm - com) < 1e-9
    assert np.abs(rec.j_unit_mm5 - j).max() / np.abs(j).max() < 1e-12


@pytest.mark.parametrize("name", ["pcb_obc", "pcb_eps", "payload_electronics_box", "sensor_housing_hex",
                                  "wedge_bracket", "gear_mechanism"])
def test_exact_float32_rounded_parts_match_to_1e6(dataset_parts, name):
    p, rec = dataset_parts[name]
    vol, com, j = _analytic_in_canonical(p, rec)
    diag = float(np.linalg.norm(rec.v.max(0) - rec.v.min(0)))
    assert abs(rec.volume_mm3 - vol) / vol < 1e-6
    assert np.linalg.norm(rec.com_can_mm - com) < 1e-5 * diag
    assert np.abs(rec.j_unit_mm5 - j).max() / np.abs(j).max() < 1e-6


@pytest.mark.parametrize("name", ["reaction_wheel", "magnetorquer_rod", "propellant_tank_sphere", "gas_tank_capsule",
                                  "ellipsoid_module", "optics_baffle_tube", "magnetometer_ring_torus",
                                  "camera_with_lens"])
def test_tessellated_parts_within_discretisation_error(dataset_parts, name):
    p, rec = dataset_parts[name]
    vol, com, j = _analytic_in_canonical(p, rec)
    rel = (vol - rec.volume_mm3) / vol
    assert 0 < rel < 1e-2                        # inscribed tessellations are always slightly smaller
    assert np.abs(rec.j_unit_mm5 - j).max() / np.abs(j).max() < 1.5e-2


def test_reference_implementation_agrees_on_every_part(dataset_parts):
    for name, (p, rec) in dataset_parts.items():
        if rec.volume_mm3 is not None:
            assert rec.ref_check["agree"], (name, rec.ref_check)


def test_fixture_outcomes(dataset_parts):
    assert dataset_parts["fixture_open_mesh"][1].status == "WITHHELD"
    assert dataset_parts["fixture_open_mesh"][1].mass_kg is None
    flipped = dataset_parts["fixture_flipped_normals"][1]
    assert flipped.status == "REPAIRED" and flipped.volume_mm3 > 0
    assert dataset_parts["fixture_two_bodies"][1].topology.components == 2


def test_dataset_totals(dataset_parts):
    packable = [r for n, (p, r) in dataset_parts.items() if p["role"] == "packable"]
    assert len(packable) == 19
    assert abs(sum(r.mass_kg for r in packable) - 2.916) < 0.001


def test_every_proxy_is_certified(dataset_parts):
    for name, (p, rec) in dataset_parts.items():
        assert rec.boxes_certified, (name, rec.boxes_detail)
        assert rec.cover.certified, (name, rec.cover.detail)


def test_proxies_contain_every_vertex(dataset_parts):
    for name, (p, rec) in dataset_parts.items():
        inside = np.zeros(len(rec.v), bool)
        for b in rec.boxes:
            inside |= np.all((rec.v >= b[:3]) & (rec.v <= b[3:]), axis=1)
        assert inside.all(), name


def test_pcb_proxy_keeps_notches(dataset_parts):
    _, rec = dataset_parts["pcb_obc"]
    total = np.prod(rec.boxes[:, 3:] - rec.boxes[:, :3], axis=1)
    assert len(rec.boxes) >= 2
    corner = np.array([44.0, 44.0, 0.0])     # inside a 7 mm notch, outside the board
    assert not any(np.all((corner >= b[:3]) & (corner <= b[3:])) for b in rec.boxes)
    del total


def test_symmetry_reduced_orientations(dataset_parts):
    assert len(dataset_parts["cross_connector_hub"][1].allowed_orients) == 1
    assert len(dataset_parts["battery_pack"][1].allowed_orients) == 3
    assert len(dataset_parts["payload_electronics_box"][1].allowed_orients) == 6
    assert len(dataset_parts["l_shaped_electronics"][1].allowed_orients) == 12
