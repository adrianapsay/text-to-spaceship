"""The Windows tools of tools/toolchain.lock.json that setup.cmd does not unpack itself, because they need Python:
CalculiX 2.23 (ccx.exe and the DLLs it loads, from nine conda-forge packages, .tar.zst inside) and BESO (one GitHub
commit's archive). Every archive is fetched from the lock's URL (or kept from an earlier run) and used only when its
size and SHA-256 are the lock's; every file taken out of a package is checked against the lock's SHA-256 too. The
layout is the lock's: packages in tools/ccx/pkgs, unpacked to tools/ccx/x/<name>/pkg, the files flat in tools/ccx
(Windows loads DLLs from the exe's folder first); BESO's archive as tools/beso/beso-<commit>.zip, unpacked beside it.

uv, Node.js and CPython come first, from setup.cmd (curl, certutil and tar ship with Windows).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .fetch import FetchError, fetch, problem, sha256_of, unpack_conda, unzip

REPO = Path(__file__).resolve().parents[4]
LOCK = REPO / "tools" / "toolchain.lock.json"


def lock(path: Path = LOCK) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))["tools"]


def setup_ccx(spec: dict, ccx_dir: Path, out=print) -> list[str]:
    """CalculiX into ccx_dir from the lock's 'ccx' entry; returns the files put in place (none when all are)."""
    files = spec["files"]
    if all(problem(ccx_dir / f, v["sha256"], v["bytes"]) is None for f, v in files.items()):
        return []
    for p in spec["packages"]:
        archive = ccx_dir / "pkgs" / p["url"].rsplit("/", 1)[1]
        how = fetch(p["url"], archive, p["sha256"], p["bytes"])
        unpacked = ccx_dir / "x" / p["name"] / "pkg"
        if how != "kept" or not unpacked.is_dir():
            shutil.rmtree(unpacked, ignore_errors=True)
            unpack_conda(archive, unpacked)
        out(f"  {p['name']} {p['version']}: {how}")
    placed = []
    for f, v in files.items():
        if problem(ccx_dir / f, v["sha256"], v["bytes"]) is None:
            continue
        found = [c for c in (ccx_dir / "x" / v["from"]).rglob(f) if c.is_file() and sha256_of(c) == v["sha256"]]
        if not found:
            raise FetchError(f"{f}: no file with the lock's SHA-256 in package {v['from']}")
        shutil.copyfile(found[0], ccx_dir / f)
        placed.append(f)
    return placed


def setup_beso(spec: dict, beso_dir: Path, needed: tuple[str, ...], out=print) -> str:
    """BESO into beso_dir/beso-<commit> from the lock's 'beso' entry; returns how its archive was got."""
    zip_path = beso_dir / f"beso-{spec['commit']}.zip"
    how = fetch(spec["url"], zip_path, spec["sha256"], spec["bytes"])
    folder = beso_dir / f"beso-{spec['commit']}"
    if how != "kept" or not all((folder / f).is_file() for f in needed):
        unzip(zip_path, beso_dir)
    missing = [f for f in needed if not (folder / f).is_file()]
    if missing:
        raise FetchError(f"{zip_path.name}: {', '.join(missing)} not in the archive")
    out(f"  BESO {spec['commit'][:7]}: {how}")
    return how


def ccx_version(exe: Path) -> str:
    """The first line ccx prints for -v ("This is Version 2.23"); ccx exits with a non-zero code there."""
    r = subprocess.run([str(exe), "-v"], capture_output=True, text=True, timeout=60, cwd=str(exe.parent),
                       check=False)
    return next((ln.strip() for ln in r.stdout.splitlines() if ln.strip()), "")


def main(argv: list[str] | None = None) -> int:
    from ..fea import ccx
    from ..gd.entrants import beso_ccx

    if sys.platform != "win32":
        print("CalculiX and BESO: the lock holds Windows builds only; skipped (the app runs without them: "
              "NGSolve does the FEA, and the CalculiX cross-check and the BESO contest entrant are left out).")
        return 0
    tools = lock()
    print("CalculiX 2.23 (conda-forge packages, checked against tools/toolchain.lock.json):")
    placed = setup_ccx(tools["ccx"], ccx.CCX_EXE.parent)
    print(f"  {len(placed)} file(s) put in place" if placed else "  already in place")
    version = ccx_version(ccx.CCX_EXE)
    if f"Version {tools['ccx']['version']}" not in version:
        print(f"  ccx -v printed {version!r}, not version {tools['ccx']['version']}")
        return 1
    print(f"  ccx -v: {version}")
    print("BESO (checked against tools/toolchain.lock.json):")
    setup_beso(tools["beso"], beso_ccx.BESO_DIR.parent, beso_ccx.BESO_FILES)
    return 0
