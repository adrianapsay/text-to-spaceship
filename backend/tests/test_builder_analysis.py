"""V3 CubeSat Builder, M2/M3: the analyses against published values, the catalog readers, the architect's picks, one
test per compatibility rule, the engine on the California design and the analysis endpoints (on an app of their
own: no optimiser starts)."""
import json
import math

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scipy.special import erfc

from t2s.api.builder import router
from t2s.builder import catalog as K
from t2s.builder import compat as C
from t2s.builder import engine as E
from t2s.builder import questions as Q
from t2s.builder import recommend as RC
from t2s.builder.analysis import adcs as AD
from t2s.builder.analysis import comms as CM
from t2s.builder.analysis import imaging as IM
from t2s.builder.analysis import orbit as O
from t2s.builder.analysis import power as PW
from t2s.builder.analysis import propulsion as PR
from t2s.builder.analysis import refs as R
from t2s.builder.analysis import structure as S
from t2s.builder.analysis import thermal as TH
from t2s.builder.catalog import parse as P
from t2s.builder.intake import apply_statement
from t2s.builder.model import new_design
from t2s.builder.store import BuilderStore

CALIFORNIA = "I want to build a satellite that photographs California from orbit."


def design(text=CALIFORNIA, **answers):
    d, _ = apply_statement(new_design(), text)
    for qid, v in answers.items():
        Q.answer(d, qid, v)
    Q.accept_defaults(d)
    return d


@pytest.fixture(scope="module")
def california():
    d = design()
    return d, E.analyse(d)


# ============================================================================================ published values
def test_sun_synchronous_inclinations_match_landsat_and_sentinel2():
    assert abs(O.sso_inclination(705.0) - 98.2) < 0.1            # USGS: Landsat 8, 705 km, 98.2°
    assert abs(O.sso_inclination(786.0) - 98.62) < 0.1           # ESA: Sentinel-2, 786 km, 98.62°
    with pytest.raises(ValueError):
        O.sso_inclination(6000.0)                                 # no sun-synchronous inclination that high


def test_the_eclipse_is_the_cylindrical_shadow():
    h, re_ = 500e3, R.RE
    expected = math.acos(math.sqrt(h * h + 2 * re_ * h) / (re_ + h)) / math.pi
    assert O.eclipse_fraction(500.0, 0.0) == pytest.approx(expected, rel=1e-12)
    assert O.eclipse_fraction(500.0, 0.0) * O.period_s(500.0) / 60 == pytest.approx(35.76, abs=0.01)
    beta_star = math.asin(re_ / (re_ + h))
    assert O.eclipse_fraction(500.0, beta_star + 0.01) == 0.0    # the orbit never enters the shadow


def test_uncoded_bpsk_needs_9_6_db_for_a_bit_error_rate_of_1e_5():
    def ber(db):
        return 0.5 * erfc(math.sqrt(10 ** (db / 10)))
    assert ber(R.EBN0_BPSK_1E5) <= 1e-5 < ber(R.EBN0_BPSK_1E5 - 0.1)


def test_the_constants_in_decibels_and_the_black_body_at_1_au():
    assert R.K_DB == pytest.approx(10 * math.log10(R.K_BOLTZ), abs=0.01)
    # a black sphere in sunlight far from the Earth: T = (S / 4σ)^¼ ≈ 278 K
    t = TH.node_temp_c(1.0, 1e9, 0.0, 0.0, 0.0, 0.0, 0.0, alpha=1.0, eps=1.0)
    assert t + 273.15 == pytest.approx((R.S0 / (4 * R.SIGMA)) ** 0.25, rel=1e-9)
    assert 277.0 < t + 273.15 < 280.0


def test_link_budget_free_space_loss():
    passes = {"max_range_km": 1000.0, "minutes_per_day": 10.0}
    radio = K.by_id("aac-clyde-space-pulsar-utrx")
    out = CM.link_calcs({"sel": {"radio_ttc": [(radio, 1)]}, "passes": passes}, "radio_ttc", "antenna_ttc", "UHF")
    c = out["comms.radio_ttc"]
    f = P.frequency_mhz(radio)
    assert c["inputs"]["L_fs"]["value"] == pytest.approx(20 * math.log10(4 * math.pi * 1e6 * f * 1e6 / R.C_LIGHT),
                                                         abs=1e-3)
    assert c["rate_bps"] <= 9600.0                                # never more than the radio's own rate


def test_lifetime_disposal_and_transfers():
    assert O.lifetime_years(600, 10, 0.05) > O.lifetime_years(500, 10, 0.05) > O.lifetime_years(400, 10, 0.05)
    assert O.lifetime_years(500, 20, 0.05) > O.lifetime_years(500, 10, 0.05)
    h = PR.altitude_for_lifetime(5.0, 10.0, 0.05)
    assert O.lifetime_years(h, 10.0, 0.05) == pytest.approx(5.0, rel=0.05)
    assert PR.hohmann_dv(500, 400) == pytest.approx(PR.hohmann_dv(400, 500), rel=1e-9)
    assert PR.hohmann_dv(500, 500) == pytest.approx(0.0, abs=1e-9)


def test_gravity_gradient_torque_and_box_inertia():
    ix, iy, iz = AD.inertia(12.0, (0.1, 0.2263, 0.366))
    assert iz == pytest.approx(12 * (0.1 ** 2 + 0.2263 ** 2) / 12)
    out = AD.adcs_calcs({"alt_km": 500.0, "mass_kg": 12.0, "size_u": 6, "dims_m": (0.1, 0.2263, 0.366),
                         "off_nadir_deg": 30.0, "sel": {}, "calcs": {}})
    gg = out["adcs.disturbance"]["parts"]["gravity_gradient"]
    r = O.semi_major(500.0)
    assert gg == pytest.approx(1.5 * R.MU / r ** 3 * (max(ix, iy, iz) - min(ix, iy, iz)) * math.sin(math.radians(60)))


def test_camera_pixels_scale_with_altitude():
    cam = K.by_id("simera-sense-multiscape100")
    at = IM.camera_at(cam, 550.0)
    assert at["gsd_m"] == pytest.approx(4.75 * 550 / 500)
    assert at["swath_km"] == pytest.approx(19.4 * 550 / 500)


def test_face_factors_of_a_nadir_pointing_box():
    ff = PW.face_factors([0.0, math.pi / 2], [0.0, 0.0], samples=3600)
    assert ff["+v"][0] == pytest.approx(1 / math.pi, abs=1e-3)   # half the orbit at cos θ: mean = 1/π
    assert ff["+n"][0] == pytest.approx(0.0, abs=1e-12)          # the Sun in the orbit plane
    assert ff["+n"][1] == pytest.approx(1.0)                     # the Sun along the orbit normal


# ============================================================================================ the catalog
def test_every_catalog_value_cites_a_source():
    assert K.validate() == []
    assert len(K.components()) >= 70


def test_the_readers_use_each_makers_units():
    assert P.frequency_mhz(K.by_id("endurosat-x-band-transmitter")) == pytest.approx(8212.5)       # GHz
    assert P.rf_power_w(K.by_id("endurosat-uhf-transceiver-ii")) == pytest.approx(10 ** 0.3)       # 33 dBm
    rate, note = P.data_rate_bps(K.by_id("satlab-srs-4"))
    assert rate == pytest.approx(5e6) and "ASSUMED" in note                                       # 5 MBd
    assert P.data_rate_bps(K.by_id("satlab-srx-8"))[0] == pytest.approx(1.4e9)                     # Gbit/s
    assert P.gain_dbi(K.by_id("satlab-sas-2"), "tx") == pytest.approx(6.1)
    assert P.band(K.by_id("isispace-vhf-uhf-antenna-1u-3u")) == {"uhf", "vhf"}
    assert P.angle_deg(K.by_id("bct-xact-15"), "pointing_accuracy") == pytest.approx(25 / 3600)    # arcsec


def test_the_sizes_makers_name():
    assert RC.stated_sizes("designed for 6-12U platforms") == [(6.0, 12.0)]
    assert RC.stated_sizes("for 'CubeSats as small as 2U'") == [(2.0, 99.0)]
    assert RC.stated_sizes("1.5U payload volume; starting from 6U") == [(6.0, 99.0)]
    assert sorted(RC.stated_sizes(K.by_id("aac-clyde-space-starbuck-nano")["fits"])) == [(2.0, 2.0), (3.0, 3.0)]
    assert RC.size_ok(K.by_id("aac-clyde-space-iadcs400"), 3) is False
    assert RC.size_ok(K.by_id("bct-xact-15"), 3) is None


# ============================================================================================ the architect
def test_ranking_follows_the_sliders():
    cheap = {"id": "a", "category": "gnss", "manufacturer": "A", "product": "a", "mass_kg": {"value": 0.2},
             "price": {"value": 1000, "currency": "EUR", "kind": "listed"}}
    light = {"id": "b", "category": "gnss", "manufacturer": "B", "product": "b", "mass_kg": {"value": 0.05},
             "price": {"value": 9000, "currency": "EUR", "kind": "listed"}}
    for_cost = RC.weights({**{k: v["default"] for k, v in RC.SLIDERS.items()}, "cost_performance": 0.0,
                           "mass_capability": 1.0})
    for_mass = RC.weights({**{k: v["default"] for k, v in RC.SLIDERS.items()}, "cost_performance": 1.0,
                           "mass_capability": 0.0})
    assert RC.rank([cheap, light], for_cost)[0][1]["id"] == "a"
    assert RC.rank([cheap, light], for_mass)[0][1]["id"] == "b"


def test_prices_compare_only_in_one_currency():
    usd = {"id": "u", "category": "gnss", "manufacturer": "U", "product": "u",
           "price": {"value": 10, "currency": "USD", "kind": "listed"}}
    eur = [{"id": f"e{i}", "category": "gnss", "manufacturer": "E", "product": f"e{i}",
            "price": {"value": 5000 + i, "currency": "EUR", "kind": "listed"}} for i in range(2)]
    ranked = RC.rank([usd, *eur], RC.weights({**{k: v["default"] for k, v in RC.SLIDERS.items()},
                                               "cost_performance": 0.0}))
    parts = {c["id"]: p for _, c, p in ranked}
    assert parts["u"]["cost"][0] == 0.0 and parts["e0"]["cost"][0] == 1.0     # 10 USD is not "cheaper"


def test_the_architect_prefers_parts_whose_numbers_it_can_check(california):
    _, a = california
    ttc = a["picks"]["radio_ttc"]
    assert ttc["items"][0]["id"] == "aac-clyde-space-pulsar-utrx"          # its power is published
    ax100 = next(x for x in ttc["alternatives"] if x["id"] == "gomspace-nanocom-ax100")
    assert "does not publish its power" in ax100["reason"]
    xact = a["picks"]["adcs"]
    assert xact["items"][0]["id"] == "bct-xact-15"                         # the only unit that meets the pointing
    assert any("does not publish its power" in f for f in xact["flags"])   # … so the gap is said, not hidden
    assert any("published loads only" in f for f in a["picks"]["solar"]["flags"])   # and the panels say so too


def test_the_california_design(california):
    _, a = california
    assert a["size_label"] == "6U" and a["failures"] == []
    o = a["orbit"]
    assert o["sso"] and o["ltdn_h"] == 10.5 and o["alt_km"] in E.ALT_SCAN
    assert abs(o["inc_deg"] - O.sso_inclination(o["alt_km"])) < 1e-9
    calcs = a["calcs"]
    assert calcs["orbit.lifetime"]["value"] >= PR.LIFETIME_MARGIN * a["mission_years"]
    assert calcs["imaging.camera_gsd"]["meets"] and calcs["imaging.bands"]["ok"]
    assert calcs["budget.data"]["ok"] and calcs["power.margin"]["ok"]
    assert calcs["budget.mass"]["value"] <= R.CDS_MASS_KG[6]
    for p in a["picks"].values():
        for it in p["items"]:
            assert it.get("placeholder") or K.by_id(it["id"]) is not None
        for alt in p["alternatives"]:
            assert alt["reason"]
    assert {c["status"] for c in a["checks"]} <= set(C.STATUS)
    assert [t["size_u"] for t in a["trade"]] == list(S.SIZES)
    assert next(t for t in a["trade"] if t["size_u"] == 3)["failures"]      # 3U is too full for this camera
    assert "not flight-ready" in a["disclaimer"]
    json.dumps(a)


def test_an_unknown_is_never_marked_compatible(california):
    designs = [california[1], E.analyse(design("measure radiation in orbit", **{"mission.type": "science"})),
               E.analyse(design(**{"comms.band": "x"}))]
    for a in designs:
        for ch in a["checks"]:
            if "not published" in ch["detail"] or "publishes no" in ch["detail"]:
                assert ch["status"] == "unknown", ch


def test_user_choices_replace_a_pick_and_keep_the_recommendation():
    d = design()
    d["selections"] = {"payload": {"component": "dragonfly-aerospace-caiman", "qty": 1}, "gnss": {"component": None}}
    d["size_u"] = 12
    a = E.analyse(d)
    assert a["size_label"] == "12U" and a["size_user"]
    p = a["picks"]["payload"]
    assert p["status"] == "user" and p["items"][0]["id"] == "dragonfly-aerospace-caiman"
    assert p["recommended"]["items"][0]["id"] == "simera-sense-multiscape100"
    assert a["picks"]["gnss"]["status"] == "none" and not a["picks"]["gnss"]["items"]


def test_propulsion_follows_the_lifetime_and_the_disposal_rule():
    high = E.analyse(design(**{"orbit.choice": "sso", "orbit.altitude_km": 700.0}))
    assert high["calcs"]["orbit.disposal"]["ok"] is False                 # would outlast the five-year rule
    assert high["picks"]["propulsion"]["items"] and "five-year" in high["picks"]["propulsion"]["why"]
    low = E.analyse(design())
    assert low["picks"]["propulsion"]["status"] == "none"
    asked = E.analyse(design(**{"propulsion.need": "deorbit"}))
    assert asked["picks"]["propulsion"]["items"]                          # you asked for one: you get one


def test_other_missions_get_their_own_payload():
    sci = E.analyse(design("measure radiation in orbit", **{"mission.type": "science"}))
    assert sci["picks"]["payload"]["status"] == "placeholder"
    assert sci["picks"]["payload"]["items"][0]["placeholder"]
    ais = E.analyse(design("receive ship AIS signals", **{"mission.type": "communications",
                                                         "comms.service": "ais_adsb"}))
    assert ais["picks"]["payload"]["status"] == "missing" and "no payload fits" in ais["failures"]


def test_open_questions_take_their_documented_defaults_and_are_listed():
    d = new_design()
    Q.answer(d, "mission.type", "earth_observation")
    a = E.analyse(d)
    open_q = {q["qid"]: q for q in a["open_questions"]}
    assert "imaging.gsd_m" in open_q and "mission.fidelity" in open_q
    assert "10" in open_q["imaging.gsd_m"]["default"] and "ASSUMED" in open_q["imaging.gsd_m"]["why"]
    assert "imaging.gsd_m" not in d["answers"]                          # the design itself is untouched
    assert a["refs"]["wgs84"]["url"].startswith("https://")             # every cited source travels with it
    assert isinstance(a["calcs"]["budget.cost"]["value"], str)


def test_the_analysis_is_cached_by_its_inputs():
    d = design()
    a1 = E.analyse(d)
    a2 = E.analyse(d)
    assert a2["cached"] and a2["inputs_hash"] == a1["inputs_hash"]
    Q.answer(d, "imaging.gsd_m", 30.0)
    a3 = E.analyse(d)
    assert a3["inputs_hash"] != a1["inputs_hash"] and not a3["cached"]


# ============================================================================================ compatibility rules
def part(cid, category, **f):
    return {"id": cid, "category": category, "manufacturer": "Test", "product": cid, **f}


EPS = part("eps", "eps", performance={"bus_voltages": {"value": "3.3 V, 5 V and 12 V regulated; configurable 3.3 – "
                                                                "18 V"}})
OBC = part("obc", "obc", interfaces={"data": ["I2C", "CAN", "LVDS"]}, supply_voltage_v={"value": "3.3 V"})


def rules(sel, calcs=None, size=3, places=None):
    pl = places or {s.id: s.place for s in RC.SLOTS}
    return C.check_design({"size": size, "sel": sel, "calcs": calcs or {}, "places": pl, "req": {}})


def by(checks, rule, item=None):
    return [c["status"] for c in checks if c["rule"] == rule and (item is None or item in c["items"])]


def test_rule_supply_voltage():
    sel = {"eps": [(EPS, 1)], "obc": [(OBC, 1)],
           "gnss": [(part("five", "gnss", supply_voltage_v={"value": "5 V"}), 1)],
           "radio_ttc": [(part("wide", "radio", supply_voltage_v={"value": "6 - 16 V"}), 1)],
           "payload": [(part("hi", "camera", supply_voltage_v={"value": "28 VDC"}), 1)],
           "radio_data": [(part("none", "radio"), 1)],
           "adcs": [(part("bare", "adcs_unit", supply_voltage_v={"value": "12", "unit": "V"}), 1)]}
    ch = rules(sel)
    assert by(ch, "voltage", "five") == ["compatible"]
    assert by(ch, "voltage", "wide") == ["compatible"]        # 12 V lies in 6–16 V
    assert by(ch, "voltage", "hi") == ["incompatible"]        # no 28 V output
    assert by(ch, "voltage", "none") == ["unknown"]           # not published
    assert by(ch, "voltage", "bare") == ["compatible"]        # "12" with unit V
    st, _ = C.supply_match(part("odd", "gnss", supply_voltage_v={"value": "7 V"}), EPS)
    assert st == "assumptions"                                 # only from the configurable output


def test_rule_data_interface_and_image_path():
    cam = part("cam", "camera", interfaces={"data": ["Data: LVDS", "Control: I2C"]})
    sel = {"obc": [(OBC, 1)], "payload": [(cam, 1)],
           "gnss": [(part("rs", "gnss", interfaces={"data": ["RS-422"]}), 1)],
           "radio_ttc": [(part("quiet", "radio"), 1)]}
    ch = rules(sel)
    assert by(ch, "data_interface", "cam") == ["compatible"]
    assert by(ch, "data_interface", "rs") == ["incompatible"]
    assert by(ch, "data_interface", "quiet") == ["unknown"]
    assert by(ch, "image_path") == ["compatible"]
    slow = part("slow", "obc", interfaces={"data": ["I2C"]})
    assert by(rules({"obc": [(slow, 1)], "payload": [(cam, 1)]}), "image_path") == ["assumptions"]


def test_rule_mechanical_fit_and_the_packing_model():
    sel = {"obc": [(part("small", "obc", dimensions_mm={"x": 90, "y": 90, "z": 10}), 1)],
           "payload": [(part("tight", "camera", dimensions_mm={"x": 98.3, "y": 98.3, "z": 176.5}), 1)],
           "gnss": [(part("huge", "gnss", dimensions_mm={"x": 120, "y": 120, "z": 50}), 1)],
           "battery": [(part("unsized", "battery"), 1)]}
    ch = rules(sel, size=6)
    assert by(ch, "mechanical", "small") == ["compatible"]
    assert by(ch, "mechanical", "tight") == ["assumptions"]    # rail envelope only: thinner walls needed
    assert by(ch, "mechanical", "huge") == ["compatible"]      # lies on its side in a 6U …
    assert by(rules(sel, size=3), "mechanical", "huge") == ["incompatible"]       # … not in a 3U
    assert by(ch, "mechanical", "unsized") == ["unknown"]
    assert by(ch, "packing_model", "tight") == ["assumptions"]   # the optimiser's Stage 1 only
    assert by(ch, "packing_model", "small") == []               # fits Stage 2 too: nothing to say
    assert by(rules(sel, size=3), "packing_model", "tight") == ["assumptions"]
    assert S.packing_fit((120, 120, 50), 3) == "too_big" and S.packing_fit((90, 90, 10), 3) == "stage2"


def test_rule_external_clearance():
    sel = {"antenna_ttc": [(part("thick", "antenna", dimensions_mm={"x": 98, "y": 98, "z": 7}), 1)],
           "sun_sensor": [(part("thin", "sun_sensor", dimensions_mm={"x": 24.66, "y": 15, "z": 3.5}), 1)],
           "solar": [(part("flat", "solar_panel"), 1)]}
    ch = rules(sel)
    assert by(ch, "clearance", "thick") == ["assumptions"]
    assert by(ch, "clearance", "thin") == ["compatible"]
    assert by(ch, "clearance", "flat") == ["unknown"]


def test_rule_temperature_ranges():
    sel = {"obc": [(part("a", "obc", operating_temp_c={"min": -10, "max": 50}), 1)],
           "gnss": [(part("b", "gnss", operating_temp_c={"min": 10, "max": 30}), 1)],
           "radio_ttc": [(part("c", "radio"), 1)]}
    calcs = {"thermal.nominal": {"value": 20.0}, "thermal.hot": {"value": 35.0}, "thermal.cold": {"value": -5.0}}
    ch = rules(sel, calcs)
    assert by(ch, "thermal", "a") == ["compatible"]
    assert by(ch, "thermal", "b") == ["assumptions"]           # nominal inside, bounds outside
    assert by(ch, "thermal", "c") == ["unknown"]
    calcs["thermal.nominal"]["value"] = 60.0
    assert by(rules(sel, calcs), "thermal", "a") == ["incompatible"]


def margin_calc(v, target=20.0, missing=()):
    return {"power.margin": {"value": v, "ok": v >= target, "positive": v >= 0, "target_pct": target},
            "power.load_avg": {"value": 3.0, "missing_parts": list(missing)}}


def test_rule_power_margin():
    assert by(rules({}, margin_calc(30.0)), "power") == ["compatible"]
    assert by(rules({}, margin_calc(5.0)), "power") == ["assumptions"]
    assert by(rules({}, margin_calc(-5.0)), "power") == ["incompatible"]
    assert by(rules({}, margin_calc(30.0, missing=["X"])), "power") == ["unknown"]


def ok_calc(cid, ok, value=1.0, **extra):
    return {cid: {"value": value, "ok": ok, "missing": None, "explain": "e", **extra}}


@pytest.mark.parametrize("cid,rule,extra", [
    ("power.battery", "battery", {}), ("budget.data", "data", {}), ("adcs.pointing", "adcs_pointing", {"need": 1.0}),
    ("adcs.momentum", "adcs_momentum", {"need": 1.0}), ("adcs.knowledge", "adcs_knowledge", {"need": 1.0}),
    ("structure.volume", "volume", {"fill_max": 0.7}), ("orbit.lifetime", "lifetime", {"mission_years": 2}),
    ("orbit.disposal", "disposal", {}), ("propulsion.dv", "propulsion", {"need": 1.0}),
    ("imaging.bands", "bands", {}), ("orbit.access", "revisit", {"revisit_h": 72.0}),
])
def test_rules_from_the_analyses(cid, rule, extra):
    base = {"power.battery_need": {"value": 1.0}}
    assert by(rules({}, {**base, **ok_calc(cid, True, **extra)}), rule) == ["compatible"]
    assert by(rules({}, {**base, **ok_calc(cid, False, **extra)}), rule) == ["incompatible"]
    unknown = {cid: {"value": None, "ok": None, "missing": "not published", "explain": "", **extra}}
    assert by(rules({}, {**base, **unknown}), rule) == ["unknown"]


def test_rules_camera_gsd_and_aperture():
    calcs = {"imaging.camera_gsd": {"value": 5.0, "meets": True, "explain": "Meets"},
             "imaging.aperture_fit": {"value": 90.0, "feasible": False, "explain": "Too small"}}
    ch = rules({}, calcs)
    assert by(ch, "gsd") == ["compatible"] and by(ch, "aperture") == ["assumptions"]   # softer, but it reaches it
    calcs["imaging.camera_gsd"] = {"value": 12.0, "meets": False, "explain": "Coarser"}
    assert by(rules({}, calcs), "aperture") == ["incompatible"]
    calcs["imaging.aperture_fit"]["feasible"] = True
    assert by(rules({}, calcs), "aperture") == ["compatible"]


def test_bands_a_maker_does_not_name_are_unknown_not_missing():
    assert IM.band_cover(K.by_id("dragonfly-aerospace-mantis"), ["rgb", "nir"]) == {"rgb": None, "nir": None}
    ms100 = IM.band_cover(K.by_id("simera-sense-multiscape100"), ["rgb", "nir", "swir"])
    assert ms100 == {"rgb": True, "nir": True, "swir": False}            # VNIR 450-900 nm leaves SWIR out
    assert IM.band_cover(K.by_id("satlantis-isim-90"), ["swir"]) == {"swir": True}


def test_orbit_and_payload_settle_on_one_consistent_design():
    a = E.analyse(design(**{"imaging.gsd_m": 5.0}))
    c = a["calcs"]
    assert c["imaging.camera_gsd"]["meets"] and c["orbit.lifetime"]["ok"]   # not a mix of two passes
    assert abs(c["orbit.inclination"]["value"] - O.sso_inclination(a["orbit"]["alt_km"])) < 1e-3   # 6 s.f.
    small = E.analyse(design(**{"imaging.gsd_m": 30.0}))
    assert small["size_label"] == "3U" and small["failures"] == []


def test_rule_mass():
    m = {"value": 5.0, "limit_kg": 6.0, "with_margin_kg": 6.0, "margin_pct": 20.0, "missing_items": []}
    assert by(rules({}, {"budget.mass": m}), "mass") == ["compatible"]
    assert by(rules({}, {"budget.mass": {**m, "with_margin_kg": 6.5}}), "mass") == ["assumptions"]
    assert by(rules({}, {"budget.mass": {**m, "missing_items": ["X"]}}), "mass") == ["unknown"]
    assert by(rules({}, {"budget.mass": {**m, "value": 6.5}}), "mass") == ["incompatible"]


def test_rule_gnss_velocity_limits():
    def gnss(text):
        return part("g", "gnss", performance={"max_altitude_or_velocity_limits": {"value": text}})
    calcs = {"orbit.speed": {"value": 7.6}}
    assert by(rules({"gnss": [(gnss("Velocity up to 9 km/s"), 1)]}, calcs), "gnss_limits") == ["compatible"]
    assert by(rules({"gnss": [(gnss("Velocity limit 600 m/s"), 1)]}, calcs), "gnss_limits") == ["incompatible"]
    assert by(rules({"gnss": [(gnss("no COCOM limitations; standard: 600 m/s"), 1)]}, calcs),
              "gnss_limits") == ["assumptions"]
    assert by(rules({"gnss": [(gnss(""), 1)]}, calcs), "gnss_limits") == ["unknown"]


def test_rule_eps_input_power():
    eps = part("e", "eps", performance={"input_power_max_w": {"value": 30}})
    gen = {"power.generation": {"value": 10.0, "panel_w": 45.0}}
    assert by(rules({"eps": [(eps, 1)]}, gen), "eps_input") == ["incompatible"]
    assert by(rules({"eps": [(eps, 1)]}, {"power.generation": {"value": 10.0, "panel_w": 20.0}}),
              "eps_input") == ["compatible"]
    assert by(rules({"eps": [(part("e2", "eps"), 1)]}, gen), "eps_input") == ["unknown"]


# ============================================================================================ endpoints
def test_the_analysis_endpoints(tmp_path):
    app = FastAPI()
    app.state.builder = BuilderStore(tmp_path)
    app.include_router(router)
    c = TestClient(app)
    did = c.post("/api/builder/designs", json={"statement": CALIFORNIA}).json()["design"]["id"]
    c.post(f"/api/builder/designs/{did}/defaults")
    a = c.get(f"/api/builder/designs/{did}/analysis").json()
    assert a["size_label"] == "6U" and a["design_version"] >= 2
    assert c.post(f"/api/builder/designs/{did}/selection", json={"slot": "nope"}).status_code == 404
    bad = c.post(f"/api/builder/designs/{did}/selection", json={"slot": "payload", "component": "bct-xact-15"})
    assert bad.status_code == 400 and "not a payload" in bad.json()["detail"]
    r = c.post(f"/api/builder/designs/{did}/selection", json={"slot": "gnss", "component": "skyfox-labs-pinav-ng-fm"})
    assert r.json()["design"]["selections"]["gnss"]["component"] == "skyfox-labs-pinav-ng-fm"
    a = c.get(f"/api/builder/designs/{did}/analysis").json()
    assert a["picks"]["gnss"]["status"] == "user"
    c.delete(f"/api/builder/designs/{did}/selection/gnss")
    assert c.get(f"/api/builder/designs/{did}").json()["design"]["selections"] == {}
    assert c.patch(f"/api/builder/designs/{did}/prefs", json={"size_u": 5}).status_code == 400
    c.patch(f"/api/builder/designs/{did}/prefs", json={"size_u": 12, "cost_performance": 2})
    d = c.get(f"/api/builder/designs/{did}").json()["design"]
    assert d["size_u"] == 12 and d["prefs"]["cost_performance"] == 1.0
    assert c.get(f"/api/builder/designs/{did}/analysis").json()["size_label"] == "12U"
    cat = c.get("/api/builder/catalog?category=camera").json()
    assert cat["components"] and all(x["category"] == "camera" for x in cat["components"])
    e = c.get("/api/builder/catalog/bct-xact-15").json()
    assert e["unpublished"] == ["power"] and "_file" not in e["component"]
    assert c.get("/api/builder/catalog/nope").status_code == 404
    assert c.get("/api/builder/meta").json()["sliders"]["cost_performance"]["default"] == 0.5


def test_numbers_are_finite(california):
    for cid, c in california[1]["calcs"].items():
        v = c["value"]
        if isinstance(v, float):
            assert np.isfinite(v), cid
