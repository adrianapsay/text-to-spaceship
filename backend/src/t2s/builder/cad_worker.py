"""Convert one CAD file (STEP, IGES or BREP) to a millimetre STL with OpenCASCADE, in a process of its own:
`python -I cad_worker.py <source> <out.stl>` prints one line of JSON — the geometry's facts, or {"error": ...}.
builder.cad runs it with a time limit, so a malformed file cannot take the app down. It imports only gmsh, netgen,
numpy and the standard library (it runs isolated, by path, outside the t2s package).

Two tessellations, in turn:
1. OpenCASCADE's own (BRepMesh, the tessellation CAD viewers display), through netgen.occ: on the makers' assemblies it
   took seconds where gmsh took minutes or failed (Optimus-40: 144 000 triangles in 13 s, volume within 0.01 %; gmsh
   stopped on a face loop it could not close), and gave far lighter meshes (SAS-2: 36 000 triangles against gmsh's
   1 000 000). It is used when its triangles' volume is within 2 % of OpenCASCADE's solids (or the file has none).
2. gmsh's surface mesh otherwise, with repairs only where needed: OpenCASCADE's shape healing changes good files —
   sewing merges an assembly's touching solids into loose shells (a maker's sun sensor lost all 3 of its solids, a
   patch antenna all 21), and removing small edges left a GNSS receiver's faces with open boundary loops that no
   surface mesh could close. So a file is meshed as it is first; the small-edge/face fixes run only when that mesh
   fails, and sewing only for a file of surfaces without solids.

Units: OpenCASCADE converts the file's length unit to millimetres on import, in both (gmsh: Geometry.OCCTargetUnit
"MM"; netgen.occ: OpenCASCADE's default; a file declaring metres reads 1000 times larger in both).
Facts: solids and surfaces found, the solids' volume and centre (uniform density), the bounding box, the tessellation
used, and for gmsh the repair used (REPAIRS) and the mesh size.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

# the repairs tried in turn: the file as it is, then OpenCASCADE's fixes without sewing, then sewing into solids
REPAIRS = (("as is", None), ("fixed", {"sewFaces": False, "makeSolids": False}), ("sewn", {}))
# gmsh's surface mesher: Delaunay. Its default (Frontal-Delaunay) stalled for over 5 minutes on one thread on a maker's
# radio (PULSAR-UTRX: 13 454 faces) that Delaunay meshed in 12 s (456 000 triangles); MeshAdapt stalled too.
DELAUNAY = 5


def convert(src: str, out: str) -> dict:
    """OpenCASCADE's tessellation when it is sound, else gmsh's surface mesh (the reason is kept)."""
    try:
        facts = tessellate_occ(src, out)
        if not facts["solids"] or abs(facts["triangle_volume_mm3"] - facts["volume_mm3"]) <= 0.02 * facts["volume_mm3"]:
            return facts
        why = (f"its triangles enclose {facts['triangle_volume_mm3']:.0f} mm³ against the solids' "
               f"{facts['volume_mm3']:.0f} mm³")
    except Exception as exc:  # noqa: BLE001 - any failure of the first tessellation: the second is tried
        why = f"{type(exc).__name__}: {exc}"
    facts = convert_gmsh(src, out)
    if "error" not in facts:
        facts["occ_note"] = why
    return facts


def tessellate_occ(src: str, out: str) -> dict:
    """OpenCASCADE's own tessellation (BRepMesh) of the file, through netgen.occ, written as a binary STL. Raises when
    netgen cannot read the file or returns data of another form than expected (its web-viewer data, order 1)."""
    import numpy as np
    from netgen.occ import OCCGeometry
    ext = Path(src).suffix.lower()
    copy = Path(out).with_name("occ_input" + {".igs": ".iges"}.get(ext, ext))   # netgen: lower-case step/stp/iges/brep
    shutil.copyfile(src, copy)
    shape = OCCGeometry(str(copy)).shape
    solids = shape.solids
    vol, com = 0.0, [0.0, 0.0, 0.0]
    for s in solids:
        m, c = s.mass, list(s.center)
        vol += m
        com = [com[i] + m * c[i] for i in range(3)]
    com = [x / vol for x in com] if vol > 0 else None
    lo, hi = (list(p) for p in shape.bounding_box)
    data = shape._webgui_data()                                   # netgen's tessellation for its web viewer
    corners = data.get("Bezier_trig_points") or []
    if data.get("order2d") != 1 or len(corners) < 3:
        raise ValueError("netgen's tessellation data is not of the expected form (order 1, three corner arrays)")
    pts = [np.asarray(corners[i], dtype=float).reshape(-1, 4) for i in range(3)]   # x, y, z, face index
    tri = np.stack([p[:, :3] for p in pts], axis=1)
    if not len(tri):
        raise ValueError("OpenCASCADE's tessellation has no triangles")
    n_faces = len(shape.faces)
    meshed = len(np.unique(pts[0][:, 3]))
    tri_vol = abs(float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0))
    _write_stl(out, tri)
    return {"solids": len(solids), "surfaces": n_faces, "volume_mm3": vol, "com_mm": com, "bbox_mm": [lo, hi],
            "tessellation": "occ", "faces_without_triangles": n_faces - meshed, "triangle_volume_mm3": tri_vol}


def _write_stl(out: str, tri) -> None:
    """A binary STL of triangles (n, 3, 3) in mm, normals from the corners' order."""
    import numpy as np
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, norm, out=np.zeros_like(n), where=norm > 0)
    rec = np.zeros(len(tri), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    with open(out, "wb") as f:
        f.write(b"text-to-spaceship: OpenCASCADE tessellation".ljust(80, b" "))
        f.write(np.uint32(len(tri)).tobytes())
        f.write(rec.tobytes())


def convert_gmsh(src: str, out: str) -> dict:
    import gmsh
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        failed = None
        for repair, heal in REPAIRS:
            gmsh.clear()
            gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
            try:
                gmsh.model.occ.importShapes(src)
            except Exception as exc:  # noqa: BLE001 - any reader failure is the file's
                return {"error": f"OpenCASCADE could not read the file ({exc})"}
            try:
                got = _attempt(gmsh, repair, heal, out)
            except Exception as exc:  # noqa: BLE001 - this attempt failed (a surface that cannot be meshed, a wire
                failed = str(exc)                         # OpenCASCADE cannot fix, a repair that cannot run): next
                continue
            if got is None:
                continue                                   # surfaces only: sewing may make them solids
            if "error" not in got:
                got.update(repair=repair, mesh_error=failed, tessellation="gmsh")
            return got
        return {"error": f"no surface mesh could be made, even after OpenCASCADE's repairs ({failed})"}
    finally:
        gmsh.finalize()


def _attempt(gmsh, repair: str, heal: dict | None, out: str) -> dict | None:
    """One repair tried on the imported file: its facts with the STL written, {"error"} for a file without geometry,
    or None for surfaces without solids before the sewing attempt. A failure raises (the next repair is tried)."""
    if heal is not None:
        try:
            gmsh.model.occ.healShapes(**heal)
        except Exception:                                 # the sewing attempt meshes the file as it is instead
            if repair != "sewn":
                raise
    gmsh.model.occ.synchronize()
    solids = gmsh.model.getEntities(3)
    surfaces = gmsh.model.getEntities(2)
    if not solids and not surfaces:
        return {"error": "the file holds no geometry (no solids or surfaces)"}
    if not solids and repair != "sewn":
        return None
    box = gmsh.model.getBoundingBox(-1, -1)
    lo, hi = list(box[:3]), list(box[3:])
    h = max(math.dist(lo, hi) / 60.0, 0.3)
    gmsh.option.setNumber("Mesh.MeshSizeMax", h)
    gmsh.option.setNumber("Mesh.MeshSizeMin", h / 10.0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
    gmsh.option.setNumber("Mesh.Algorithm", DELAUNAY)
    gmsh.option.setNumber("Mesh.Binary", 1)
    gmsh.model.mesh.generate(2)
    vol, com = 0.0, [0.0, 0.0, 0.0]
    for d, t in solids:
        m = gmsh.model.occ.getMass(d, t)
        c = gmsh.model.occ.getCenterOfMass(d, t)
        vol += m
        com = [com[i] + m * c[i] for i in range(3)]
    com = [x / vol for x in com] if vol > 0 else None
    gmsh.write(out)
    return {"solids": len(solids), "surfaces": len(surfaces), "volume_mm3": vol, "com_mm": com, "bbox_mm": [lo, hi],
            "mesh_h_mm": h}


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
