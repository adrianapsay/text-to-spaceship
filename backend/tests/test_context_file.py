"""The pickled search context the workers load must follow every validation rule, not only the context id."""
from t2s.service.context import SearchContext, load_context, write_context


def _ctx(spec_sig: str) -> SearchContext:
    c = SearchContext.__new__(SearchContext)          # only the fields write_context / pickling need
    c.__dict__.update(ctx_id="psig-csig-lsig", spec_sig=spec_sig)
    return c


def test_a_rules_change_under_the_same_context_id_gets_its_own_file(tmp_path):
    old, new = write_context(_ctx("v23rules"), tmp_path), write_context(_ctx("v24rules"), tmp_path)
    assert old != new
    assert load_context(old).spec_sig == "v23rules" and load_context(new).spec_sig == "v24rules"
    assert write_context(_ctx("v24rules"), tmp_path) == new              # unchanged rules: the same file, reused
