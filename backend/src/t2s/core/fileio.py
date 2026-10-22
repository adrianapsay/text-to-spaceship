"""Atomic text writes for files that another process may be reading (progress and result files)."""
from __future__ import annotations

import os
import time
from pathlib import Path


def atomic_write_text(path, text: str, retries: int = 100, wait_s: float = 0.02) -> None:
    """Write through a temporary file and os.replace. On Windows the replace fails with PermissionError while
    another process has the target open (the coordinator polling a progress file), so it is retried for up to
    about 2 s before the error is raised."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for k in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if k == retries - 1:
                raise
            time.sleep(wait_s)
