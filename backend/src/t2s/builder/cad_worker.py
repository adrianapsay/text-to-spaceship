"""Convert one CAD file (STEP, IGES or BREP) to a millimetre STL with OpenCASCADE (through gmsh), in a process of its
own: `python -I cad_worker.py <source> <out.stl>` prints one line of JSON — the geometry's facts, or {"error": ...}.
builder.cad runs it with a time limit, so a malformed file cannot take the app down. It imports only gmsh and the
standard library (it runs isolated, by path, outside the t2s package).

Units: OpenCASCADE converts the file's length unit to millimetres on import (Geometry.OCCTargetUnit = "MM").
Facts: solids and surfaces found, the solids' volume and centre (uniform density), the bounding box, whether shape
healing ran, and the surface mesh size used for the STL.
"""
from __future__ import annotations

import json
import math
import sys


def convert(src: str, out: str) -> dict:
    import gmsh
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        try:
            gmsh.model.occ.importShapes(src)
        except Exception as exc:  # noqa: BLE001 - any reader failure is the file's
            return {"error": f"OpenCASCADE could not read the file ({exc})"}
        healed = True
        try:
            gmsh.model.occ.healShapes()
        except Exception:  # noqa: BLE001 - healing is best effort; say it did not run
            healed = False
        gmsh.model.occ.synchronize()
        solids = gmsh.model.getEntities(3)
        surfaces = gmsh.model.getEntities(2)
        if not solids and not surfaces:
            return {"error": "the file holds no geometry (no solids or surfaces)"}
        vol, com = 0.0, [0.0, 0.0, 0.0]
        for d, t in solids:
            m = gmsh.model.occ.getMass(d, t)
            c = gmsh.model.occ.getCenterOfMass(d, t)
            vol += m
            com = [com[i] + m * c[i] for i in range(3)]
        com = [x / vol for x in com] if vol > 0 else None
        box = gmsh.model.getBoundingBox(-1, -1)
        lo, hi = list(box[:3]), list(box[3:])
        diag = math.dist(lo, hi)
        h = max(diag / 60.0, 0.3)
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.MeshSizeMin", h / 10.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
        gmsh.option.setNumber("Mesh.Binary", 1)
        gmsh.model.mesh.generate(2)
        gmsh.write(out)
        return {"solids": len(solids), "surfaces": len(surfaces), "volume_mm3": vol, "com_mm": com,
                "bbox_mm": [lo, hi], "healed": healed, "mesh_h_mm": h}
    finally:
        gmsh.finalize()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(json.dumps({"error": "usage: cad_worker <source> <out.stl>"}))
        return 2
    try:
        out = convert(argv[1], argv[2])
    except Exception as exc:  # noqa: BLE001 - reported to the parent as data
        out = {"error": f"conversion failed ({type(exc).__name__}: {exc})"}
    print(json.dumps(out))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
