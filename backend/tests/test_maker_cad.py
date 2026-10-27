"""The makers' CAD on another computer (get_cad.py): the recorded files are the ones docs/V3.md §5.4 lists; each is
used only when its size and SHA-256 are the recorded ones, imported through the app's checks with the recorded model,
never downloaded without a yes or when a folder is named, and skipped once imported."""
import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
import trimesh

import t2s.builder.maker_cad as M
import t2s.core.fetch as F
from t2s.builder import catalog as K
from t2s.builder.cad import CadStore

REPO = Path(__file__).resolve().parents[2]
PART = "aac-clyde-space-ss200"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stl_box(dims) -> bytes:
    return trimesh.creation.box(extents=dims).export(file_type="stl")


@pytest.fixture
def maker_zip():
    """A maker-style archive of two models of the SS200: its box, and a larger fixture the importer would pick by
    itself (the larger of two equally named files)."""
    dims = K.dims_mm(K.by_id(PART))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SS200/box.stl", stl_box(dims))
        z.writestr("SS200/fixture.stl", stl_box([d * 1.5 for d in dims]))
    data = buf.getvalue()
    return {"id": PART, "name": "AAC Clyde Space SS200 (test)", "url": "https://example.invalid/SS200.zip",
            "file": "SS200.zip", "bytes": len(data), "sha256": sha(data), "model": "SS200/box.stl",
            "fetched": "2026-10-27"}, data


@pytest.fixture(autouse=True)
def no_downloads(monkeypatch):
    def refuse(url, dest):
        raise AssertionError(f"tried to download {url}")
    monkeypatch.setattr(F, "download", refuse)


def test_the_recorded_files_are_the_ones_the_docs_list():
    files = M.sources()
    doc = (REPO / "docs" / "V3.md").read_text(encoding="utf-8")
    assert len(files) == 14 and len({s["id"] for s in files}) == 14
    for s in files:
        assert K.by_id(s["id"]) is not None, s["id"]
        assert s["url"].startswith("https://") and unquote(Path(urlparse(s["url"]).path).name) == s["file"]
        assert len(s["sha256"]) == 64 and int(s["sha256"], 16) >= 0 and s["bytes"] > 0
        assert s["file"] in doc, s["file"]
    assert f"{sum(s['bytes'] for s in files) / 1e6:.1f} MB" == "148.7 MB" and "148.7 MB" in doc


def test_a_file_is_copied_checked_and_imported_with_the_recorded_model(tmp_path, maker_zip):
    s, data = maker_zip
    (tmp_path / "copy" / PART).mkdir(parents=True)
    (tmp_path / "copy" / PART / s["file"]).write_bytes(data)
    store = CadStore(tmp_path / "cad")
    lines = []
    [r] = M.get([s], store, source_dir=tmp_path / "copy", out=lines.append)
    assert (r["fetch"], r["import"], r["ok"]) == ("copied", "imported", True)
    e = store.entry(PART)
    assert e["origin"] == "manufacturer" and e["sha256"] == s["sha256"] and e["source_url"] == s["url"]
    assert e["archive_member"] == "SS200/box.stl" and e["archive_models"] == ["SS200/box.stl", "SS200/fixture.stl"]
    assert sorted(e["extents_mm"]) == pytest.approx(sorted(K.dims_mm(K.by_id(PART))), abs=1e-6)
    assert (tmp_path / "cad" / "downloads" / PART / s["file"]).read_bytes() == data
    rec = json.loads((tmp_path / "cad" / "downloads" / "downloads.json").read_text(encoding="utf-8"))
    assert [(x["id"], x["sha256"], x["how"]) for x in rec] == [(PART, s["sha256"], "copied")]
    [again] = M.get([s], store, source_dir=tmp_path / "copy", out=lines.append)
    assert (again["fetch"], again["import"]) == ("kept", "already")
    assert store.entry(PART)["imported"] == e["imported"]                      # not imported a second time


def test_a_file_that_is_not_the_recorded_one_is_refused(tmp_path, maker_zip):
    s, data = maker_zip
    (tmp_path / "copy").mkdir()
    (tmp_path / "copy" / s["file"]).write_bytes(data + b"changed")
    store = CadStore(tmp_path / "cad")
    [r] = M.get([s], store, source_dir=tmp_path / "copy", out=lambda *a: None)
    assert r["fetch"] == "failed" and r["import"] == "-" and "not the recorded file" in r["detail"]
    assert store.entry(PART) is None and not (tmp_path / "cad" / "downloads" / PART / s["file"]).exists()


def test_a_named_folder_without_the_file_never_downloads(tmp_path, maker_zip):
    s, _ = maker_zip
    (tmp_path / "empty").mkdir()
    [r] = M.get([s], CadStore(tmp_path / "cad"), source_dir=tmp_path / "empty", out=lambda *a: None)
    assert r["fetch"] == "failed" and r["detail"].startswith("not in ")


def test_main_lists_and_asks_before_downloading(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "CadStore", lambda: CadStore(tmp_path / "cad"))
    assert M.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "14 files, 148.7 MB" in out and "licence terms apply" in out
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "n")
    assert M.main(["--only", PART]) == 1
    assert "Nothing downloaded." in capsys.readouterr().out
    assert asked and "Download 1 file(s), 0.2 MB, from the makers' websites?" in asked[0]
    with pytest.raises(SystemExit):
        M.main(["--only", "no-such-part"])
    with pytest.raises(SystemExit):
        M.main(["--from", str(tmp_path / "missing")])
