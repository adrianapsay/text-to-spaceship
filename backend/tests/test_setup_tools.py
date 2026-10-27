"""Setting V3 up on another computer: checked downloads (size and SHA-256, HTTPS only), safe unpacking, CalculiX and
BESO from the lock's archives, and setup.cmd fetching exactly what tools/toolchain.lock.json records."""
import hashlib
import io
import re
import tarfile
import zipfile
from pathlib import Path

import pytest

import t2s.core.fetch as F
from t2s.core import toolchain as T

REPO = Path(__file__).resolve().parents[2]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fake_conda(files: dict) -> bytes:
    """A .conda package: a zip holding pkg-<name>.tar.zst with these files."""
    from compression import zstd

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("metadata.json", '{"conda_pkg_format_version": 2}')
        z.writestr("pkg-fake-1.0-0.tar.zst", zstd.compress(tar_buf.getvalue()))
        z.writestr("info-fake-1.0-0.tar.zst", zstd.compress(b""))
    return buf.getvalue()


def test_a_copy_is_kept_only_when_it_is_the_recorded_file(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"maker file")
    dest = tmp_path / "out" / "file.bin"
    url = "https://example.invalid/file.bin"
    assert F.fetch(url, dest, sha(b"maker file"), 10, source=src) == "copied"
    assert dest.read_bytes() == b"maker file"
    assert F.fetch(url, dest, sha(b"maker file"), 10, source=src) == "kept"         # checked, not copied again
    other = tmp_path / "other.bin"
    with pytest.raises(F.FetchError, match="not the recorded file"):
        F.fetch(url, other, sha(b"something else"), None, source=src)
    with pytest.raises(F.FetchError, match="10 bytes where 11"):
        F.fetch(url, other, sha(b"maker file"), 11, source=src)
    assert not other.exists() and not list(tmp_path.glob("*.part"))


def test_a_download_that_is_not_the_recorded_file_is_deleted(tmp_path, monkeypatch):
    served = {"data": b"published"}
    monkeypatch.setattr(F, "download", lambda url, dest: Path(dest).write_bytes(served["data"]))
    dest = tmp_path / "file.zip"
    assert F.fetch("https://example.invalid/file.zip", dest, sha(b"published"), 9) == "downloaded"
    served["data"] = b"changed by the maker"
    dest2 = tmp_path / "file2.zip"
    with pytest.raises(F.FetchError, match="SHA-256"):
        F.fetch("https://example.invalid/file2.zip", dest2, sha(b"published"))
    assert not dest2.exists() and not (tmp_path / "file2.zip.part").exists()
    assert dest.read_bytes() == b"published"


def test_downloads_are_https_only(tmp_path):
    with pytest.raises(F.FetchError, match="only HTTPS"):
        F.download("http://example.invalid/file.zip", tmp_path / "f")


def test_unzip_refuses_unsafe_paths(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ok/a.txt", "a")
        z.writestr("../evil.txt", "x")
    (tmp_path / "a.zip").write_bytes(buf.getvalue())
    with pytest.raises(F.FetchError, match="unsafe path"):
        F.unzip(tmp_path / "a.zip", tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_calculix_files_come_out_of_their_packages_checked(tmp_path):
    exe, dll = b"ccx binary", b"a library"
    conda = fake_conda({"Library/bin/ccx.exe": exe, "Library/bin/libfake.dll": dll, "Library/bin/unused.dll": b"-"})
    ccx_dir = tmp_path / "ccx"
    (ccx_dir / "pkgs").mkdir(parents=True)
    (ccx_dir / "pkgs" / "fake-1.0-0.conda").write_bytes(conda)            # as kept by an earlier run
    spec = {"packages": [{"name": "fake", "version": "1.0", "url": "https://example.invalid/w/fake-1.0-0.conda",
                          "sha256": sha(conda), "bytes": len(conda)}],
            "files": {"ccx.exe": {"from": "fake", "sha256": sha(exe), "bytes": len(exe)},
                      "libfake.dll": {"from": "fake", "sha256": sha(dll), "bytes": len(dll)}}}
    assert sorted(T.setup_ccx(spec, ccx_dir, out=lambda *a: None)) == ["ccx.exe", "libfake.dll"]
    assert (ccx_dir / "ccx.exe").read_bytes() == exe and (ccx_dir / "x" / "fake" / "pkg" / "Library").is_dir()
    assert not (ccx_dir / "unused.dll").exists()
    assert T.setup_ccx(spec, ccx_dir, out=lambda *a: None) == []                # in place: nothing to do
    (ccx_dir / "ccx.exe").unlink()
    spec["files"]["ccx.exe"]["sha256"] = sha(b"another build")
    with pytest.raises(F.FetchError, match="no file with the lock's SHA-256"):
        T.setup_ccx(spec, ccx_dir, out=lambda *a: None)


def test_beso_unpacks_from_its_commit_archive(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in ("beso_main.py", "beso_lib.py", "LICENSE"):
            z.writestr(f"beso-abc123/{f}", f"# {f}")
    data = buf.getvalue()
    (tmp_path / "beso-abc123.zip").write_bytes(data)
    spec = {"commit": "abc123", "url": "https://example.invalid/abc123", "sha256": sha(data), "bytes": len(data)}
    assert T.setup_beso(spec, tmp_path, ("beso_main.py", "beso_lib.py"), out=lambda *a: None) == "kept"
    assert (tmp_path / "beso-abc123" / "beso_main.py").read_text() == "# beso_main.py"
    with pytest.raises(F.FetchError, match="beso_plots.py not in the archive"):
        T.setup_beso(spec, tmp_path, ("beso_plots.py",), out=lambda *a: None)


def test_setup_cmd_fetches_what_the_lock_records():
    lock = T.lock()
    text = (REPO / "setup.cmd").read_text(encoding="utf-8")
    fetched = {m[1]: (m[0], m[2]) for m in re.findall(r"call :fetch (\S+) (\S+) ([0-9a-f]{64})", text)}
    for tool in ("uv", "node"):
        url, digest = lock[tool]["url"], lock[tool]["sha256"]
        name = url.rsplit("/", 1)[1]
        assert fetched[name] == (url, digest)
        assert f"tools\\downloads\\{name}" in text                       # the zip setup.cmd unpacks is that one
    assert f"uv {lock['uv']['version']}" in text and f"Node.js {lock['node']['version']}" in text
    assert f"uv python install {lock['cpython']['version']}" in text
    assert len(fetched) == 2


def test_the_lock_names_a_package_for_every_calculix_file():
    ccx = T.lock()["ccx"]
    names = {p["name"] for p in ccx["packages"]}
    assert "ccx.exe" in ccx["files"] and all(v["from"] in names for v in ccx["files"].values())
    assert all(p["url"].startswith("https://conda.anaconda.org/conda-forge/win-64/") for p in ccx["packages"])
