"""Checked downloads for setting up a computer: a file is fetched over HTTPS (or copied from a file the user names)
and kept only when its size and SHA-256 equal the recorded ones; anything else is deleted and refused. Used by
setup_fea.py (CalculiX and BESO, tools/toolchain.lock.json) and get_cad.py (the makers' CAD, builder/maker_cad.json).

Downloads go through curl, as the files were first fetched (Windows 10 1803 and later, macOS and Linux include it),
else through urllib; both refuse to leave HTTPS, redirects included.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

CHUNK = 1 << 20
TIMEOUT_S = 900.0


class FetchError(RuntimeError):
    """A file that could not be fetched, or that is not the recorded one (its size or SHA-256 differs)."""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def problem(path: Path, sha256: str, size: int | None = None) -> str | None:
    """Why the file at path is not the recorded one, or None when its size and SHA-256 are the recorded ones."""
    path = Path(path)
    if not path.is_file():
        return "missing"
    n = path.stat().st_size
    if size is not None and n != size:
        return f"{n:,} bytes where {size:,} were recorded"
    got = sha256_of(path)
    if got != sha256.lower():
        return f"SHA-256 {got} where {sha256.lower()} was recorded"
    return None


def download(url: str, dest: Path) -> None:
    """Download url to dest over HTTPS only (redirects too)."""
    if not url.startswith("https://"):
        raise FetchError(f"{url}: only HTTPS downloads are allowed")
    curl = shutil.which("curl")
    try:
        if curl:
            r = subprocess.run([curl, "-fsSL", "--retry", "2", "--proto", "=https", "--proto-redir", "=https",
                                "-o", str(dest), url],
                               capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
            if r.returncode:
                raise FetchError(f"{url}: download failed (curl exit {r.returncode}: {r.stderr.strip()})")
            return
        with urllib.request.urlopen(url, timeout=60) as resp:
            if not resp.geturl().startswith("https://"):
                raise FetchError(f"{url}: redirected off HTTPS to {resp.geturl()}")
            with open(dest, "wb") as f:
                shutil.copyfileobj(resp, f, CHUNK)
    except subprocess.TimeoutExpired as exc:
        raise FetchError(f"{url}: no complete download within {TIMEOUT_S:.0f} s") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(f"{url}: download failed ({exc})") from exc


def fetch(url: str, dest: Path, sha256: str, size: int | None = None, source: Path | None = None) -> str:
    """Put the recorded file at dest and say how: "kept" (already there and checked), "copied" (from source, a file
    the user named) or "downloaded" (from url). A copy or download that is not the recorded file is deleted and
    FetchError raised; dest is then left as it was."""
    dest = Path(dest)
    if problem(dest, sha256, size) is None:
        return "kept"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    try:
        if source is not None:
            if not Path(source).is_file():
                raise FetchError(f"{source}: no such file")
            shutil.copyfile(source, part)
        else:
            download(url, part)
        why = problem(part, sha256, size)
        if why:
            raise FetchError(f"{source or url}: not the recorded file ({why})")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(dest)
    return "copied" if source is not None else "downloaded"


def unzip(zip_path: Path, into: Path) -> list[Path]:
    """Every file of a .zip into `into`, refusing absolute paths, '..' and links; returns the files written."""
    out = []
    into = Path(into)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or ":" in info.filename or "\\" in info.filename:
                raise FetchError(f"{zip_path}: unsafe path in the archive ({info.filename})")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise FetchError(f"{zip_path}: a link in the archive ({info.filename})")
            if info.is_dir():
                continue
            target = into.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as f:
                shutil.copyfileobj(src, f, CHUNK)
            out.append(target)
    return out


def unpack_conda(conda: Path, into: Path) -> None:
    """A conda package (.conda: a zip holding pkg-<name>.tar.zst) unpacked into `into` (tarfile's 'data' filter:
    no absolute paths, '..', links out of `into` or special files)."""
    from compression import zstd

    with zipfile.ZipFile(conda) as z:
        pkg = [n for n in z.namelist() if n.startswith("pkg-") and n.endswith(".tar.zst")]
        if len(pkg) != 1:
            raise FetchError(f"{conda}: not a .conda package (no single pkg-*.tar.zst)")
        with z.open(pkg[0]) as raw, zstd.ZstdFile(raw) as zf, tarfile.open(fileobj=zf, mode="r|") as tar:
            tar.extractall(into, filter="data")
