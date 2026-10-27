"""The makers' CAD files the Builder was checked with (docs/V3.md §5.4), for setting up another computer.

get_cad.py fetches each file from its maker's site (or copies it from a folder the user names, such as
data/builder/cad/downloads copied from a computer that has them), keeps it only when its size and SHA-256 equal the
ones recorded in maker_cad.json, and imports it through the same checks as an import in the app
(CadStore.import_file), so the same STL results. The app itself never downloads CAD: this is a command the user runs.
The files are the makers' (their licence terms apply) and stay in data/builder/cad, which git ignores.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from ..core.fetch import FetchError, fetch, problem
from ..core.fileio import atomic_write_text
from .cad import CadStore
from .model import now_iso

LIST = Path(__file__).with_name("maker_cad.json")
NOTICE = ("These files are the makers' own: their licence terms apply. They stay in data/builder/cad on this "
          "computer, which git ignores (never committed or pushed).")


def sources() -> list[dict]:
    """The recorded files: id (the catalog part), name, url, file, bytes, sha256, model (the archive member the
    importer takes; None for a file that is the model itself), fetched (date)."""
    return json.loads(LIST.read_text(encoding="utf-8"))["files"]


def target(store: CadStore, s: dict) -> Path:
    return store.root / "downloads" / s["id"] / s["file"]


def local_copy(folder: Path, s: dict) -> Path | None:
    """The file in a folder the user names: <folder>/<part>/<file> (the layout of data/builder/cad/downloads), or
    <folder>/<file>."""
    for p in (Path(folder) / s["id"] / s["file"], Path(folder) / s["file"]):
        if p.is_file():
            return p
    return None


def imported(store: CadStore, s: dict) -> bool:
    """Already imported from this very file with the same model, and its STL is in place."""
    e = store.entry(s["id"])
    return bool(e and e.get("origin") == "manufacturer" and e.get("sha256") == s["sha256"]
                and e.get("archive_member") == s["model"] and (store.root / e["file"]).is_file())


def _record(store: CadStore, s: dict, how: str) -> None:
    """downloads.json beside the files: where each came from, its size and SHA-256, and when."""
    p = store.root / "downloads" / "downloads.json"
    try:
        rows = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        rows = []
    rows = [r for r in rows if r.get("id") != s["id"]]
    rows.append({"id": s["id"], "name": s["name"], "url": s["url"], "file": s["file"], "bytes": s["bytes"],
                 "sha256": s["sha256"], "how": how, "at": now_iso()})
    atomic_write_text(p, json.dumps(rows, indent=1, ensure_ascii=False))


def _verdict(e: dict) -> str:
    bad = [c["name"] for c in e["checks"] if c["ok"] is False]
    unsure = [c["name"] for c in e["checks"] if c["ok"] is None]
    return (f"{e['faces']:,} triangles" + (f"; checks failed: {', '.join(bad)}" if bad else "")
            + (f"; to verify: {', '.join(unsure)}" if unsure else ""))


def get(items: list[dict], store: CadStore | None = None, source_dir: Path | None = None, out=print) -> list[dict]:
    """Fetch and import each file. One result per file: id, fetch (kept / copied / downloaded / failed), import
    (imported / already / failed / -), ok (the import's own verdict) and detail."""
    store = store or CadStore()
    results = []
    for n, s in enumerate(items, 1):
        r = {"id": s["id"], "fetch": "failed", "import": "-", "ok": None, "detail": ""}
        results.append(r)
        out(f"[{n}/{len(items)}] {s['name']}: {s['file']} ({s['bytes'] / 1e6:.1f} MB)")
        src = None
        if source_dir is not None:
            src = local_copy(source_dir, s)
            if src is None and problem(target(store, s), s["sha256"], s["bytes"]):
                r["detail"] = f"not in {source_dir}"
                out(f"    not found in {source_dir}")
                continue
        try:
            r["fetch"] = fetch(s["url"], target(store, s), s["sha256"], s["bytes"], source=src)
        except (FetchError, OSError) as exc:
            r["detail"] = str(exc)
            out(f"    {exc}")
            continue
        if r["fetch"] != "kept":
            _record(store, s, r["fetch"])
        if imported(store, s):
            e = store.entry(s["id"])
            r.update({"import": "already", "ok": e["ok"], "detail": _verdict(e)})
            out(f"    already imported from this file: {r['detail']}")
            continue
        out("    importing (OpenCASCADE in its own process; large assemblies take a minute or more)")
        try:
            e = store.import_file(s["id"], s["file"], target(store, s).read_bytes(), "manufacturer", s["url"])
            if s["model"] and e.get("archive_member") != s["model"]:
                e = store.choose_model(s["id"], s["model"])
        except Exception as exc:  # noqa: BLE001 - the reason is reported and the next file goes on
            r.update({"import": "failed", "detail": f"{type(exc).__name__}: {exc}"})
            out(f"    import failed: {r['detail']}")
            continue
        r.update({"import": "imported", "ok": e["ok"], "detail": _verdict(e)})
        out(f"    imported: {r['detail']}")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="get_cad.py", description="Fetch the makers' CAD for the Builder's parts "
                                 "(docs/V3.md section 5.4) and import it through the app's checks.")
    ap.add_argument("--from", dest="source", type=Path, metavar="FOLDER",
                    help="take the files from FOLDER (e.g. data/builder/cad/downloads copied from another computer) "
                         "instead of downloading them")
    ap.add_argument("--only", nargs="+", metavar="PART", help="these parts only (their ids, as --list shows)")
    ap.add_argument("--list", action="store_true", help="list the files and stop")
    ap.add_argument("--yes", action="store_true", help="download without asking first")
    a = ap.parse_args(argv)
    items = sources()
    if a.only:
        unknown = sorted(set(a.only) - {s["id"] for s in items})
        if unknown:
            ap.error(f"no recorded file for {', '.join(unknown)} (see --list)")
        items = [s for s in items if s["id"] in a.only]
    if a.source is not None and not a.source.is_dir():
        ap.error(f"--from {a.source}: no such folder")
    for s in items:
        print(f"  {s['id']:32} {s['file'][:52]:52} {s['bytes'] / 1e6:6.1f} MB  {urlparse(s['url']).netloc}")
    print(f"  {len(items)} files, {sum(s['bytes'] for s in items) / 1e6:.1f} MB. {NOTICE}")
    if a.list:
        return 0
    store = CadStore()
    need = [s for s in items if problem(target(store, s), s["sha256"], s["bytes"])]
    if need and a.source is None and not a.yes:
        mb = sum(s["bytes"] for s in need) / 1e6
        try:
            answer = input(f"Download {len(need)} file(s), {mb:.1f} MB, from the makers' websites? [y/N] ")
        except EOFError:                  # no console to answer from: nothing is downloaded without a yes
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing downloaded.")
            return 1
    results = get(items, store, a.source)
    done = [r for r in results if r["import"] in ("imported", "already")]
    failed = [r for r in results if r not in done]
    print(f"\n{len(done)} of {len(results)} parts have the maker's CAD"
          + (f"; not done: {', '.join(r['id'] for r in failed)} (run get-cad again to retry)" if failed else "")
          + ". The Catalog tab shows each import's checks.")
    return 0 if not failed else 1
