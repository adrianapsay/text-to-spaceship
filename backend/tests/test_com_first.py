"""V2 centre-of-mass-first mode (Balance the Spacecraft and the bracket budget both at 100): brackets of any length
built to wherever the parts end up, and full COM centring along Z."""
import numpy as np
import pytest

from t2s.core import formfactor
from t2s.mfg.rules import MFG_REACH, bracket_options


def _decode(model, k):
    n = model.n
    return model.decode(list(np.argsort(k[:n])), k[n:2 * n], k[2 * n:])


def test_beyond_40_mm_only_metal_am_brackets_exist():
    flat = {"flat_share": 1.0, "symmetric": False, "elongated": False, "curved": False, "face_mm": (40.0, 30.0),
            "extent_mm": 20.0}
    assert [o.kind for o in bracket_options(flat, 20.0, True)] == ["sheet", "metal_am", "metal_am"]
    assert bracket_options(flat, 41.0, True) == []                          # the default reach: 40 mm
    far = bracket_options(flat, 150.0, True, reach=np.inf)
    assert [o.kind for o in far] == ["metal_am", "metal_am"] and [o.fallback for o in far] == [False, True]
    assert bracket_options(flat, 150.0, False, reach=np.inf) == []          # budget 0: no bracket that long
    assert bracket_options(flat, MFG_REACH, True, reach=np.inf)[0].kind == "sheet"


def test_the_mode_needs_both_sliders_at_100():
    from t2s.constraints.stage2_model import com_first_mode
    assert com_first_mode({"balance": 100}, 4)
    assert not com_first_mode({"balance": 99}, 4)
    assert not com_first_mode({"balance": 100}, 3)
    assert not com_first_mode({}, 4)


@pytest.fixture(scope="module")
def recs():
    from test_decoder_mount import _synthetic
    return _synthetic(0.54)


@pytest.fixture
def six_u():
    formfactor.set_form_factor("6U")
    yield
    formfactor.set_form_factor("3U")


def test_com_first_centres_the_com_fully_whatever_the_com_key(recs):
    """3U at 54 %: the same chromosomes, their COM key asking for the minimal shift. Without the mode the parts move
    just far enough to bring the COM inside the CDS box (to 69.5 mm); in the mode toward full centring, as far as the
    room allows — where the stack is at the +Z end plate the room is ample and the COM ends on the centre."""
    from t2s.constraints.stage2_model import COM_BOX_Z, COM_SHIFT_MARGIN, Stage2Model
    rng = np.random.default_rng(3)
    keys = [rng.random(3 * len(recs) + 3) for _ in range(10)]
    for k in keys:
        k[-1] = 0.0                                         # the COM key: the minimal shift
    com = {}
    for cf in (False, True):
        model = Stage2Model(recs, "default", am_level=4, com_first=cf)
        com[cf] = []
        for k in keys:
            res = _decode(model, k)
            m = res.meta
            assert m.get("com_first", False) is cf                          # the layout says which rules found it
            if m["unmounted"] or res.unplaced or "com_z_unshifted_mm" not in m:
                continue
            assert m["com_z_unshifted_mm"] < -(COM_BOX_Z - COM_SHIFT_MARGIN)   # packed from −Z: below the box
            hw = [(x[1], x[2]) for x in model.stack_hardware(m)]
            com[cf].append(model._com_z(res.poses, hw))
    assert len(com[False]) >= 5 and len(com[True]) >= 5
    assert all(abs(z) >= COM_BOX_Z - COM_SHIFT_MARGIN - 0.01 for z in com[False])
    assert sum(abs(z) < 0.5 for z in com[True]) >= len(com[True]) // 2
    assert np.mean(np.abs(com[True])) < np.mean(np.abs(com[False])) - 30.0


def test_a_part_far_from_its_wall_gets_a_long_metal_am_bracket_only_in_the_mode(recs, six_u):
    """6U at 54 %: a part alone, its mounting side facing the −X wall 100 mm away. Under the standard rules it has no
    bracket (beyond the 40 mm reach); in the mode it gets a metal-AM bracket to that wall, its reserved box from the
    wall to the part."""
    from t2s.constraints.stage2_model import Stage2Model
    from t2s.core.rotations import ROTATIONS_F
    out = {}
    for cf in (False, True):
        model = Stage2Model(recs, "default", am_level=4, com_first=cf)
        pid, o = next((p, o) for p in model.ids if p in model.pads for o in model.allowed[p]
                      if (model.pads[p][2] * ROTATIONS_F[o][:, model.pads[p][1]])[0] < -0.99)
        b = model.parts[pid].oriented(o)                    # the part's boxes with its mounting layer
        lo_b, hi_b = b[:, :3].min(0), b[:, 3:].max(0)
        wall = model.inner[0][0]
        t = np.array([wall + 100.0 - lo_b[0], -(lo_b[1] + hi_b[1]) / 2, -(lo_b[2] + hi_b[2]) / 2])
        out[cf] = model.mount_check([(pid, o, t)], {"mode": "default"})[1][pid]
    assert not out[False]["ok"] and "within 40 mm" in out[False]["how"]
    br = out[True]
    assert br["ok"] and br["kind"] == "metal_am" and br["target_kind"] == "wall" and br["gap_mm"] > 100.0
    assert br["reserve"][0] == pytest.approx(wall) and br["reserve"][3] > wall + 100.0


def test_the_coordinator_restarts_the_search_when_the_mode_turns_on_or_off(tmp_path):
    from test_search_until_pause import make_coord, make_ctx
    c = make_coord(tmp_path, stage=2)
    c.ctx = make_ctx(stage=2)
    reasons = []
    c._refresh_inputs = lambda reason, bump_parts=True: reasons.append(reason)
    c._drop_saved_brackets = lambda text: None
    c.apply_settings({"sliders": {"bracket_budget": 100}})          # a budget step: new inputs, the mode still off
    assert not c._com_first() and reasons[-1].startswith("bracket budget")
    c.apply_settings({"sliders": {"balance": 100}})
    assert c._com_first() and reasons[-1] == "centre of mass first: on"
    n = len(reasons)
    c.apply_settings({"sliders": {"space": 10}})                    # another goal: a re-score, no new search
    assert len(reasons) == n
    c.apply_settings({"sliders": {"balance": 99}})
    assert not c._com_first() and reasons[-1] == "centre of mass first: off"
    c.apply_settings({"stage": 1, "sliders": {"balance": 100}})      # Stage 1 has no brackets
    assert not c._com_first()


def test_the_mode_enters_the_search_signatures_only_when_on(recs):
    from t2s.service.context import build_context
    off = build_context(recs, 2, am_level=4)
    off2 = build_context(recs, 2, am_level=4, com_first=False)
    on = build_context(recs, 2, am_level=4, com_first=True)
    assert (off.ctx_id, off.spec_sig) == (off2.ctx_id, off2.spec_sig)       # the other contexts keep their archives
    assert on.ctx_id != off.ctx_id and on.spec_sig != off.spec_sig
    assert on.stage2_model().com_first and not off.stage2_model().com_first
    assert not build_context(recs, 1, com_first=True).com_first             # Stage 1 has no brackets
