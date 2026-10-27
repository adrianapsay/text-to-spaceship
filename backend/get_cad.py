"""Fetch the makers' CAD for the Builder's parts (docs/V3.md §5.4) and import it through the app's checks.

    uv run python get_cad.py [--from FOLDER] [--only PART ...] [--list] [--yes]

Each file comes from its maker's site (or, with --from, from a folder such as data/builder/cad/downloads copied from
another computer) and is used only when its size and SHA-256 equal the recorded ones. The files are the makers'
(their licence terms apply): they stay in data/builder/cad, which git ignores.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from t2s.builder.maker_cad import main

if __name__ == "__main__":
    sys.exit(main())
