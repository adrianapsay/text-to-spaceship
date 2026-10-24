"""V2 WS6: the bill of materials (report/bom.py, GET /api/layouts/{id}/bom). Every item of the layout with its mass and
the mass's source; fasteners and spacer washers aggregated; parts + hardware equal to the layout's metrics.mass_kg
(the frame listed, not included); unknown item kinds (rods, spacers of a later model) listed with their mass."""
import copy
import csv
import io
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from t2s.api.app import create_app
from t2s.constraints.stage2_model import Stage2Model
from t2s.mfg.rules import FASTENER_MASS_KG
from t2s.report.bom import CSV_COLUMNS, bom, bom_csv, bom_from_layout
from t2s.service.coordinator import Coordinator, LayoutEntry, jsonable

F = FASTENER_MASS_KG


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
def mixed(recs):
    """A Stage 2 decode whose brackets include a direct mount, a metal-AM bracket and another kind."""
    for level in (2, 3, 1):
        m = Stage2Model(recs, "soft", am_level=level)
        rng = np.random.default_rng(level)
        for _ in range(400):
            k = rng.random(m.dim)
            n = m.n
            r = m.decode(list(np.argsort(k[:n], kind="stable")), k[n:2 * n], k[2 * n:])
            kinds = {b["kind"] for b in r.meta.get("brackets", [])}
            if {"direct", "metal_am"} <= kinds and kinds - {"direct", "metal_am"}:
                return r
    pytest.fail("no decode with direct, metal-AM and another bracket kind")


def _entry(r, scale=1.0, designs=None, lid="L-0042"):
    meta = jsonable(copy.deepcopy(r.meta))
    if designs is not None:
        meta["bracket_designs"] = designs
    return LayoutEntry(id=lid, hash="h", stage=2, mode="default", status="VALIDATED", parts_sig="p", constraint_sig="c",
                       poses=r.poses, geo={"length_used_mm": 150.0, "span_mm": 140.0}, validation={"certified": True},
                       meta=meta, part_scale=scale)


def _coord(recs, entries):
    """A coordinator with the archive, records and project order only (no workers, no event loop): enough for
    layout_json, _compute_physics, rec_at and the endpoint."""
    c = Coordinator.__new__(Coordinator)
    c.records = dict(recs)
    c._scaled, c._qual, c.ctx = {}, {}, None
    c.store = SimpleNamespace(entries={pid: SimpleNamespace(units=r.units, units_confirmed=True) for pid, r in recs.items()},
                              settings={"target_com_mm": [0.0, 0.0, 0.0]})
    c.archive = {e.id: e for e in entries}

    async def _noop():
        return None
    c.start = c.stop = _noop
    for e in entries:
        c._compute_physics(e)
    return c


def _rows(b, group=None, kind=None):
    return [r for r in b["items"] if (group is None or r["group"] == group) and (kind is None or r["kind"] == kind)]


def test_parts_plus_hardware_is_the_layout_mass_and_fasteners_are_one_row(recs, mixed):
    e = _entry(mixed)
    c = _coord(recs, [e])
    b = bom(c, e)
    t = b["totals"]
    assert t["matches_metrics"] and abs(t["assembly_kg"] - e.metrics["mass_kg"]) < 1e-9
    assert abs(t["hardware_kg"] - e.metrics["hardware_mass_kg"]) < 1e-9
    assert t["frame_kg"] == pytest.approx(e.metrics["frame_mass_kg"]) and not _rows(b, "structure")[0]["in_total"]
    assert t["with_frame_kg"] == pytest.approx(t["assembly_kg"] + t["frame_kg"])
    brs = e.meta["brackets"]
    # one fastener row: every bracket's fasteners, the ASSUMED mass each
    fast = _rows(b, kind="fastener")
    assert len(fast) == 1 and fast[0]["qty"] == sum(x["fasteners"] for x in brs) and fast[0]["unit_mass_kg"] == F
    assert fast[0]["mass_source"] == "ASSUMED" and fast[0]["name"].startswith("M3")
    # direct mounts: no bracket row; their washer stacks aggregated (4 per mount, same envelope → one row)
    direct = [x for x in brs if x["kind"] == "direct"]
    stacks = _rows(b, kind="washer_stack")
    assert sum(r["qty"] for r in stacks) == 4 * len(direct)
    assert all(r["item_ids"] and r["unit_mass_kg"] > 0 for r in stacks)
    # every other bracket: one row, its solid without the fasteners
    others = [x for x in brs if x["kind"] != "direct"]
    rows = _rows(b, "brackets")
    assert len(rows) == len(others)
    for x in others:
        r = next(r for r in rows if r["part_id"] == x["pid"])
        assert r["unit_mass_kg"] == pytest.approx(x["mass_kg"] - x["fasteners"] * F, abs=1e-12)
        assert r["mass_source"] == ("ESTIMATE" if x["kind"] in ("metal_am", "cradle") else
                                    "catalogue" if x["kind"] == "clamp" else "exact")
        if x["kind"] == "metal_am":
            assert r["process"] == "L-PBF metal AM" and r["material"].startswith("AlSi10Mg")
    # the hardware rows add up to the brackets' masses in the layout (fasteners included there)
    hw = sum(r["total_mass_kg"] for r in b["items"] if r["group"] in ("brackets", "hardware") and r["in_total"])
    assert hw == pytest.approx(sum(x["mass_kg"] for x in brs), abs=1e-12)
    # item numbers 1…n, parts first in the project's order, every row's total = unit × qty
    assert [r["item_no"] for r in b["items"]] == list(range(1, len(b["items"]) + 1))
    order = [p for p in c.store.entries if p in {q[0] for q in mixed.poses}]
    assert [r["part_id"] for r in _rows(b, "parts")] == order
    for r in b["items"]:
        if r["unit_mass_kg"] is not None:
            assert r["total_mass_kg"] == pytest.approx(r["unit_mass_kg"] * r["qty"])
    # the 3D render ids: parts by part id, brackets and washer stacks by their extra item id, each in one row only
    ids = {it["id"] for it in c.layout_json(e)["extra_items"]}
    assert all(set(r["item_ids"]) <= ids for r in b["items"] if r["group"] in ("brackets", "hardware"))
    assert all(r["item_ids"] == [r["part_id"]] for r in _rows(b, "parts"))
    owners = [i for r in b["items"] for i in r["item_ids"]]
    assert len(owners) == len(set(owners)) and ids <= set(owners)
    assert fast[0]["item_ids"] == []                       # fasteners are not modelled as solids


def test_a_designed_bracket_replaces_its_estimate_and_a_failed_one_keeps_it(recs, mixed):
    am = [x for x in mixed.meta["brackets"] if x["kind"] == "metal_am"]
    x = am[0]
    solid = 0.0068
    d = {"pid": x["pid"], "mass_kg": solid + 3 * F, "solid_mass_kg": solid, "fastener_mass_kg": 3 * F,
         "com_mm": x["com_mm"], "inertia_kgm2": x["inertia_kgm2"], "cost_rel": 20.0, "passed": True,
         "label": "metal-AM bracket designed by TEST (volume fraction 0.03)"}
    designs = {x["pid"]: d}
    if len(am) > 1:
        designs[am[1]["pid"]] = {"pid": am[1]["pid"], "passed": False, "reason": "no solid"}   # failed: estimate kept
    e = _entry(mixed, designs=designs)
    c = _coord(recs, [e])
    b = bom(c, e)
    assert b["totals"]["matches_metrics"]
    r = next(r for r in _rows(b, "brackets") if r["part_id"] == x["pid"])
    assert r["mass_source"] == "designed" and r["designed"] and r["passed"]
    assert r["unit_mass_kg"] == pytest.approx(solid) and "TEST" in r["description"]
    if len(am) > 1:
        r2 = next(r for r in _rows(b, "brackets") if r["part_id"] == am[1]["pid"])
        assert r2["mass_source"] == "ESTIMATE" and not r2["designed"]
    assert _rows(b, kind="fastener")[0]["qty"] == sum(y["fasteners"] for y in mixed.meta["brackets"])


def test_part_size_and_user_masses_follow_the_metrics(recs, mixed):
    user = dict(recs)
    pid = next(p for p, _, _ in mixed.poses if not p.startswith("pcb"))
    u = copy.copy(recs[pid])
    u.mass_override_kg, u.mass_source = 0.5, "USER_MASS"
    user[pid] = u
    e = _entry(mixed, scale=0.8)
    c = _coord(user, [e])
    b = bom(c, e)
    assert b["totals"]["matches_metrics"]
    rows = {r["part_id"]: r for r in _rows(b, "parts")}
    assert rows[pid]["unit_mass_kg"] == 0.5 and rows[pid]["mass_source"] == "USER_MASS"
    other = next(p for p in rows if p != pid)
    assert rows[other]["unit_mass_kg"] == pytest.approx(recs[other].mass_kg * 0.8 ** 3)
    assert "80 % size" in rows[other]["description"] and any("80 %" in n for n in b["notes"])


def test_endpoint_json_and_csv(recs, mixed):
    e = _entry(mixed)
    c = _coord(recs, [e])
    with TestClient(create_app(c)) as client:
        j = client.get("/api/layouts/L-0042/bom").json()
        assert j["layout_id"] == "L-0042" and j["totals"]["matches_metrics"]
        assert [r["item_no"] for r in j["items"]] == [r["item_no"] for r in bom(c, e)["items"]]
        r = client.get("/api/layouts/L-0042/bom", params={"format": "csv"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert 'filename="bom_L-0042.csv"' in r.headers["content-disposition"]
        assert client.get("/api/layouts/L-9999/bom").status_code == 404
        assert client.get("/api/layouts/L-0042/bom", params={"format": "xml"}).status_code == 400
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    lines = list(csv.reader(io.StringIO(text[1:])))
    assert lines[2] == CSV_COLUMNS
    items = [x for x in lines[3:] if x and x[0].isdigit()]
    assert len(items) == len(j["items"])
    total = next(x for x in lines if len(x) > 7 and x[1] == "TOTAL" and x[2].startswith("parts + hardware"))
    assert float(total[7]) == pytest.approx(j["totals"]["assembly_kg"], abs=1e-6)
    assert sum(float(x[7]) for x in items if x[9] == "yes") == pytest.approx(j["totals"]["assembly_kg"], abs=1e-5)


def _layout(extra, stage=2, frame=(), metrics_mass=None):
    return {"id": "L-7", "stage": stage, "mode": "default", "part_scale": 1.0,
            "poses": [{"part_id": "a", "orient": 0, "t_um": [0, 0, 0]}, {"part_id": "b", "orient": 0, "t_um": [0, 0, 0]}],
            "extra_items": extra, "metrics": {"mass_kg": metrics_mass}, "stage2": {"frame": list(frame)}}


PARTS = {"a": {"name": "box_a", "mass_kg": 0.2, "mass_source": "ASSUMED", "density_kg_m3": 2700.0, "subsystem": "power",
               "extents_mm": [10.0, 20.0, 30.0]},
         "b": {"name": "board_b", "mass_kg": None, "mass_source": "WITHHELD", "density_kg_m3": None, "subsystem": None}}
RODS = [{"kind": "rod", "id": f"rod{s}", "min": [34.0, 34.0, -30.0], "max": [37.2, 37.2, 10.0]}
        for s in ("++", "+-", "-+", "--")]


def test_rods_frame_and_kinds_a_later_model_adds():
    # rods only as keep-outs: listed with their count and length, no mass, not in the totals
    b = bom_from_layout(_layout([], frame=RODS), PARTS, ["b", "a"], frame_mass_kg=0.97)
    rod = _rows(b, kind="rod")[0]
    assert rod["qty"] == 4 and rod["unit_mass_kg"] is None and not rod["in_total"] and "40 mm long" in rod["description"]
    assert [r["part_id"] for r in _rows(b, "parts")] == ["b", "a"]              # the project's order
    assert b["totals"]["parts_kg"] == pytest.approx(0.2) and b["totals"]["withheld"] == ["board_b"]
    assert b["totals"]["frame_kg"] == 0.97 and b["totals"]["with_frame_kg"] == pytest.approx(1.17)
    assert b["totals"]["matches_metrics"] is None and rod["item_no"] in b["totals"]["not_modelled"]
    # rods and spacers carried as extra items with a mass: aggregated, counted, and the keep-outs not listed twice
    extra = [{"id": f"L-7-rod{k}", "kind": "rod", "label": "PC/104 rod M3", "material": "steel (ASSUMED)",
              "process": "catalogue", "for_part": None, "mass_kg": 0.004} for k in range(4)]
    extra += [{"id": f"L-7-sp{k}", "kind": "spacer", "label": "spacer tube 5 mm", "material": "aluminium (ASSUMED)",
               "process": "catalogue", "for_part": "b", "mass_kg": 0.001} for k in range(8)]
    b = bom_from_layout(_layout(extra, frame=RODS, metrics_mass=0.2 + 4 * 0.004 + 8 * 0.001), PARTS, ["a", "b"], 0.97)
    rods = _rows(b, kind="rod")
    assert len(rods) == 1 and rods[0]["qty"] == 4 and rods[0]["total_mass_kg"] == pytest.approx(0.016)
    sp = _rows(b, kind="spacer")[0]
    assert sp["qty"] == 8 and sp["for_parts"] == ["b"] and len(sp["item_ids"]) == 8
    assert b["totals"]["matches_metrics"] and b["totals"]["hardware_kg"] == pytest.approx(0.024)


def test_manufacturable_design_items_and_stage_1():
    extra = [
        {"id": "L-7-b01", "kind": "bracket", "process": "metal_am", "for_part": "a", "mass_kg": 0.012,
         "material": "AlSi10Mg (ASSUMED)", "label": "conformal metal-AM bracket (AM)", "mount_type": "conformal metal-AM bracket"},
        {"id": "L-7-b02", "kind": "direct", "process": "direct", "for_part": "b", "mass_kg": 0.0094,
         "material": "steel fasteners / washers (ASSUMED)", "label": "4 × M3 with spacer washers", "mount_type": "direct"},
        {"id": "L-7-s01", "kind": "bracket", "process": "catalogue", "for_part": "b", "mass_kg": 0.006,
         "material": "aluminium / steel (ASSUMED)", "label": "4 × PC/104 spacers", "mount_type": "PC/104 spacer set (4)"},
    ]
    b = bom_from_layout(_layout(extra, metrics_mass=0.2 + 0.012 + 0.0094 + 0.006), PARTS, ["a", "b"])
    assert b["totals"]["matches_metrics"]
    br = _rows(b, "brackets")
    assert len(br) == 1 and br[0]["unit_mass_kg"] == 0.012 and "fasteners" in br[0]["description"]
    assert {r["name"] for r in _rows(b, "hardware")} == {"4 × M3 with spacer washers", "4 × PC/104 spacers"}
    assert not _rows(b, kind="fastener")                     # fasteners are inside these masses: not split out
    s1 = bom_from_layout(_layout([], stage=1, metrics_mass=0.2), PARTS, ["a", "b"], frame_mass_kg=None)
    assert [r["group"] for r in s1["items"]] == ["parts", "parts"] and s1["totals"]["matches_metrics"]
    assert any("Stage 1" in n for n in s1["notes"])
    assert bom_csv(s1).count("\r\n") >= 6
