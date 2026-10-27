"""Put CalculiX 2.23 and BESO in tools/ccx and tools/beso (Windows), as pinned in tools/toolchain.lock.json: every
archive and every file is checked against its recorded SHA-256. setup.cmd runs it; it skips what is in place.

    uv run python setup_fea.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from t2s.core.toolchain import main

if __name__ == "__main__":
    sys.exit(main())
