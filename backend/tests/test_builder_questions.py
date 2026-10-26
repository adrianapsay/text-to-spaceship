"""V3 CubeSat Builder, M1: the adaptive questionnaire, the mission statement, "I don't know", the design store and
the REST endpoints (on an app of their own: no optimiser starts)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from t2s.api.builder import router
from t2s.builder import questions as Q
from t2s.builder.intake import apply_statement, read_statement
from t2s.builder.model import new_design, value
from t2s.builder.store import BuilderStore

CALIFORNIA = "I want to build a satellite that photographs California from orbit."


def test_a_new_design_starts_with_the_mission_purpose():
    d = new_design()
    todo = Q.pending(d)
    assert todo[0].id == "mission.type"
    assert not any(q.section == "payload" and q.id.startswith("imaging.") for q in todo)   # not yet: no mission type
    c = Q.completeness(d)
    assert c["answered"] == 0 and c["total"] == len(todo) and not c["complete"]


def test_the_california_sentence_becomes_confirmable_answers():
    found = read_statement(CALIFORNIA)
    assert [f["qid"] for f in found] == ["mission.type", "target.region"]
    assert found[0]["value"] == "earth_observation" and "photograph" in found[0]["why"]
    d, _ = apply_statement(new_design(), CALIFORNIA)
    assert value(d, "mission.type") == "earth_observation"
    r = d["requirements"]["target.region"]
    assert r["value"]["name"] == "California" and r["source"] == "statement" and r["value"]["lat_max"] == 42.0
    nxt = Q.pending(d)
    assert nxt[0].id == "mission.fidelity"                       # the purpose is answered by the statement
    assert any(q.id == "imaging.gsd_m" for q in nxt) and not any(q.id == "science.instrument" for q in nxt)


def test_an_ambiguous_or_empty_statement_decides_nothing():
    assert read_statement("") == []
    assert [f["qid"] for f in read_statement("photograph and measure the earth")] == []   # a tie: 1 to 1
    assert read_statement("measure radiation and photograph the earth")[0]["value"] == "science"     # 2 to 1
    assert read_statement("I want to test a new thruster")[0]["value"] == "tech_demo"


def test_the_questions_adapt_and_switching_back_restores_the_answers():
    d = new_design()
    Q.answer(d, "mission.type", "earth_observation")
    Q.answer(d, "imaging.gsd_m", 5.0)
    assert value(d, "imaging.gsd_m") == 5.0
    Q.answer(d, "mission.type", "science")
    assert "imaging.gsd_m" not in d["requirements"]                     # the imaging question no longer applies
    assert any(q.id == "science.instrument" for q in Q.pending(d))
    assert any(q.id == "payload.mass_kg" for q in Q.pending(d))          # a custom payload is described by the user
    Q.answer(d, "mission.type", "earth_observation")
    assert value(d, "imaging.gsd_m") == 5.0                              # the answer was kept


def test_i_dont_know_takes_the_default_and_says_why():
    d = new_design()
    Q.answer(d, "mission.type", "earth_observation")
    Q.answer(d, "imaging.subject", ["urban"])
    Q.answer(d, "imaging.gsd_m", unknown=True)
    r = d["requirements"]["imaging.gsd_m"]
    assert r["value"] == 3.0 and r["source"] == "default" and "ASSUMED" in r["note"]
    Q.answer(d, "imaging.subject", ["weather"])                          # a default follows what it depends on
    assert d["requirements"]["imaging.gsd_m"]["value"] == 250.0
    Q.answer(d, "imaging.bands", unknown=True)
    assert d["requirements"]["imaging.bands"]["value"] == ["rgb", "tir"]


def test_bad_answers_are_refused_with_a_reason():
    d = new_design()
    with pytest.raises(ValueError, match="choose one of"):
        Q.answer(d, "mission.type", "moon base")
    Q.answer(d, "mission.type", "earth_observation")
    with pytest.raises(ValueError, match="between 0.3 and 2000 m"):
        Q.answer(d, "imaging.gsd_m", 0.01)
    with pytest.raises(ValueError, match="does not apply"):
        Q.answer(d, "science.instrument", "radiation")
    with pytest.raises(KeyError):
        Q.answer(d, "no.such.question", 1)
    with pytest.raises(ValueError):
        Q.answer(d, "target.region", {"lat_min": 40, "lat_max": 30, "lon_min": 0, "lon_max": 10})


def test_accepting_the_defaults_answers_everything_that_applies():
    d, _ = apply_statement(new_design(), CALIFORNIA)
    Q.accept_defaults(d)
    assert Q.pending(d) == [] and Q.completeness(d)["complete"]
    assert value(d, "orbit.choice") == "recommend" and value(d, "comms.station")["name"] == "UC Berkeley"
    assert Q.pending(d, expert=True)                                     # advanced questions are still open
    Q.accept_defaults(d, expert=True)
    assert Q.pending(d, expert=True) == []
    assert value(d, "orbit.ltdn_h") == 10.5 and value(d, "imaging.geolocation_m") == 20.0   # 2 × 10 m pixels


def test_the_orbit_questions_follow_the_choice():
    d = new_design()
    Q.answer(d, "mission.type", "communications")
    Q.answer(d, "orbit.choice", "custom")
    ids = [q.id for q in Q.pending(d, expert=True)]
    assert "orbit.altitude_km" in ids and "orbit.inclination_deg" in ids and "orbit.ltdn_h" not in ids
    Q.answer(d, "orbit.choice", "iss")
    ids = [q.id for q in Q.pending(d, expert=True)]
    assert "orbit.altitude_km" not in ids
    Q.answer(d, "launch.environment", unknown=True)
    assert value(d, "launch.environment") == "nanoracks"


def test_designs_are_saved_with_their_earlier_versions(tmp_path):
    s = BuilderStore(tmp_path)
    d = new_design("demo")
    s.save(d)
    Q.answer(d, "mission.type", "astronomy")
    s.save(d)
    assert s.load(d["id"])["requirements"]["mission.type"]["value"] == "astronomy"
    assert s.versions(d["id"]) == [1] and s.load_version(d["id"], 1)["requirements"] == {}
    assert [x["id"] for x in s.list()] == [d["id"]]
    with pytest.raises(KeyError):
        s.load("D-20260101-zzzzzz")                                       # not an id: never a path
    with pytest.raises(KeyError):
        s.load("../../etc")


def test_the_rest_endpoints(tmp_path):
    app = FastAPI()
    app.state.builder = BuilderStore(tmp_path)
    app.include_router(router)
    c = TestClient(app)
    r = c.post("/api/builder/designs", json={"statement": CALIFORNIA}).json()
    did = r["design"]["id"]
    assert [f["qid"] for f in r["findings"]] == ["mission.type", "target.region"]
    assert r["view"]["next"]["id"] == "mission.fidelity" and r["view"]["next"]["default"] == "conceptual"
    r = c.post(f"/api/builder/designs/{did}/answer", json={"qid": "mission.fidelity", "unknown": True}).json()
    req = next(x for x in r["view"]["requirements"] if x["key"] == "mission.fidelity")
    assert req["value"] == "conceptual" and req["source"] == "default"
    assert c.post(f"/api/builder/designs/{did}/answer", json={"qid": "imaging.gsd_m", "value": -1}).status_code == 400
    assert c.post(f"/api/builder/designs/{did}/answer", json={"qid": "nope", "value": 1}).status_code == 404
    assert c.get("/api/builder/designs/D-20260101-abcdef").status_code == 404
    r = c.post(f"/api/builder/designs/{did}/defaults").json()
    assert r["view"]["next"] is None and r["view"]["completeness"]["complete"]
    assert len(c.get(f"/api/builder/designs/{did}/questions?expert=1").json()["questions"]) > \
        len(c.get(f"/api/builder/designs/{did}/questions").json()["questions"])
    assert c.get("/api/builder/designs").json()["designs"][0]["mission_type"] == "earth_observation"
    assert c.get("/api/builder/meta").json()["stations"][0]["name"] == "UC Berkeley"
