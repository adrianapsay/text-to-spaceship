"""Start the TEXT-TO-SPACESHIP backend on http://127.0.0.1:8765 (localhost only).

    uv run python run_server.py [--project NAME] [--islands N] [--no-search] [--add FILE.stl ...]

--add copies STL files into the project's inbox; they appear in the app and ask for a units confirmation.
If frontend/dist exists (npm run build), the app is served at the same address.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default="default")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--islands", type=int, default=None, help="search worker processes (default: min(6, cores-4))")
    ap.add_argument("--validators", type=int, default=2)
    ap.add_argument("--no-search", action="store_true", help="do not start searching automatically")
    ap.add_argument("--add", nargs="*", default=[], help="STL files to drop into the project inbox")
    ap.add_argument("--fresh", action="store_true",
                    help="test projects only (name starts with 'e2e' or 'test'): forget parts, settings and layouts "
                         "but keep the analysis cache")
    a = ap.parse_args()

    import uvicorn

    from t2s.api.app import create_app
    from t2s.service.project import PROJECTS, ProjectStore

    if a.fresh:
        if not a.project.startswith(("e2e", "test")):
            sys.exit("--fresh is only allowed for projects named e2e* or test*")
        folder = PROJECTS / a.project
        if folder.exists():
            for p in folder.iterdir():
                if p.name != "cache":
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
            print(f"fresh project {folder} (analysis cache kept)")

    if a.add:
        store = ProjectStore(a.project)
        for f in a.add:
            src = Path(f)
            if src.suffix.lower() != ".stl" or not src.is_file():
                sys.exit(f"not an STL file: {f}")
            shutil.copy2(src, store.inbox / src.name)
            print(f"queued {src.name} in {store.inbox}")
    app = create_app(project=a.project, n_islands=a.islands, n_validators=a.validators, auto_start=not a.no_search)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="info", ws_ping_interval=20)


if __name__ == "__main__":
    main()
