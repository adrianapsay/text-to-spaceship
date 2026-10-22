"""STL reading and writing (binary and ASCII). float32 coordinates are preserved exactly."""
import struct

import numpy as np

UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}


def read_stl_bytes(data: bytes) -> tuple[np.ndarray, str]:
    """Return (triangles float64 array of shape (n, 3, 3) holding exact float32 values, format)."""
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * n:
            rec = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
            arr = np.frombuffer(data, dtype=rec, count=n, offset=84)
            return arr["v"].astype(np.float64), "binary"
    text = data.decode("ascii", errors="replace")
    if "facet" not in text and "vertex" not in text:
        raise ValueError("not a recognisable STL file (neither binary layout nor ASCII facets)")
    toks = text.split()
    verts = []
    i = 0
    nt = len(toks)
    while i < nt:
        if toks[i] == "vertex" and i + 3 < nt:
            verts.append((float(toks[i + 1]), float(toks[i + 2]), float(toks[i + 3])))
            i += 4
        else:
            i += 1
    if len(verts) % 3 != 0 or not verts:
        raise ValueError(f"ASCII STL has {len(verts)} vertices, not a multiple of 3")
    tri = np.array(verts, dtype=np.float32).astype(np.float64).reshape(-1, 3, 3)
    return tri, "ascii"


def stl_bytes(vertices: np.ndarray, faces: np.ndarray, header: str = "t2s") -> bytes:
    tri = vertices[faces].astype(np.float32)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(ln > 0, n / np.where(ln > 0, ln, 1), 0).astype(np.float32)
    rec = np.zeros(len(faces), dtype=np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")]))
    rec["normal"] = n
    rec["v"] = tri
    return header.encode("ascii", "replace")[:80].ljust(80, b" ") + struct.pack("<I", len(faces)) + rec.tobytes()


def write_binary_stl(path, vertices: np.ndarray, faces: np.ndarray, header: str = "t2s") -> None:
    data = stl_bytes(vertices, faces, header)
    if hasattr(path, "write"):
        path.write(data)
        return
    with open(path, "wb") as fh:
        fh.write(data)
