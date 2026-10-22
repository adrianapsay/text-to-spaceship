import json
from pathlib import Path

import pytest

from t2s.parts.build import build_part

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic"


@pytest.fixture(scope="session")
def manifest():
    return json.loads((DATA / "manifest.json").read_text())


@pytest.fixture(scope="session")
def dataset_parts(manifest):
    parts = {}
    for i, p in enumerate(manifest["parts"]):
        parts[p["name"]] = (p, build_part((DATA / p["file"]).read_bytes(), p["name"], f"p{i:02d}", file=p["file"]))
    return parts
