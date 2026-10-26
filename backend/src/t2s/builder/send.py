"""Send to Optimization: a Builder design becomes a new optimiser project (V2) — never overwriting one.

What is sent: every part inside the structure (place "internal"), one STL per unit — the CAD the user imported
(manufacturer or reconstructed) or else a simplified box of its published size (a placeholder cube when none is
published) — with
* its catalog mass as a fixed mass (the optimiser shows it as the user's mass); a part whose mass is not published
  gets the optimiser's default density instead (ASSUMED, listed);
* its subsystem, millimetre units (confirmed), unlocked;
and the project settings: the CubeSat size, the launch environment, the target centre of mass at the centre.

The project is data/projects/builder-<mission>[-n]; its builder.json records the design, version and inputs it came
from, each optimiser part's catalog id, slot and geometry origin, what was not packed, and every constraint the
optimiser does not enforce. The optimiser packs 3U, 6U and 12U only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.fileio import atomic_write_text
from ..service.project import PROJECTS, ProjectStore
from . import catalog as K
from .analysis import structure as S
from .cad import CadStore
from .model import now_iso, slug

SUBSYSTEM = {"camera": "payload", "payload": "payload", "adcs_unit": "adcs", "reaction_wheel": "adcs",
             "magnetorquer": "adcs", "star_tracker": "adcs", "sun_sensor": "adcs", "gnss": "electronics",
             "obc": "electronics", "radio": "electronics", "antenna": "electronics", "eps": "power",
             "battery": "power", "solar_panel": "power", "propulsion": "tanks", "structure": "structure"}
FORM = {3: "3U", 6: "6U", 12: "12U"}
LAUNCH = ("gevs", "spacex", "nanoracks")


class SendError(ValueError):
    """The design cannot be sent as it is, with the reason."""


def project_name(design: dict, root: Path = PROJECTS) -> str:
    base = f"builder-{slug(design.get('name') or 'mission', 24)}"
    name, k = base, 2
    while (root / name).exists():
        name = f"{base}-{k}"
        k += 1
    return name


def unenforced(analysis: dict, sent: list[dict], external: list[dict], frame: list[dict] | None = None) -> list[str]:
    """The constraints the optimiser does not know about, in plain words."""
    out = []
    for f in frame or []:
        out.append(f"The structure is the optimiser's own frame model (2 mm walls, 8.5 mm corner rails), not the "
                   f"selected {f['name']}" + (f" ({f['mass_kg']:.3f} kg)" if f.get("mass_kg") else "") +
                   ": its geometry and mass are not the catalog's.")
    if external:
        kg = sum((e["mass_kg"] or 0.0) for e in external)
        out.append(f"External hardware is not packed: {', '.join(sorted({e['name'] for e in external}))} "
                   f"({kg:.3f} kg) — not in the optimiser's mass or centre of mass.")
    looking = [p["name"] for p in sent if p["category"] in ("camera", "star_tracker", "sun_sensor")]
    if looking:
        out.append(f"Fields of view are not enforced: {', '.join(sorted(set(looking)))} must see out of the satellite "
                   "(the camera through the nadir end); the optimiser does not know which face a part looks through.")
    out.append("Each part's centre of mass is taken at the centre of its geometry (uniform density): the makers do "
               "not publish centres of mass.")
    simple = [p["name"] for p in sent if p["origin"] in ("bbox", "placeholder")]
    if simple:
        out.append(f"Simplified shapes stand in for parts without imported CAD: {', '.join(sorted(set(simple)))}.")
    unmassed = [p["name"] for p in sent if p["mass_kg"] is None]
    if unmassed:
        out.append(f"No published mass (the optimiser's default density is used, ASSUMED): "
                   f"{', '.join(sorted(set(unmassed)))}.")
    out.append("Connectors, harness routing, PC/104 stack connectors and rods between these modules, thermal paths "
               "and access for integration are not modelled for Builder parts.")
    out.append("The design margins of the Builder's mass budget are not added: the optimiser sees the parts' "
               "published masses only.")
    return out


def send(design: dict, analysis: dict, cad: CadStore, root: Path = PROJECTS) -> dict:
    """Write the optimiser project for a design and its current analysis; returns what was sent."""
    size = analysis["size_u"]
    if size not in FORM:
        raise SendError(f"the optimiser packs 3U, 6U and 12U; this design is {S.label(size)} (choose a size in the "
                        "Trade Study)")
    sent, external, frame, warnings = [], [], [], []
    for slot_info in analysis["slots"]:
        p = analysis["picks"].get(slot_info["id"])
        if not p or not p["items"]:
            continue
        for it in p["items"]:
            rec = {"name": it["name"], "catalog_id": it["id"], "slot": p["slot"], "category": it["category"],
                   "mass_kg": it.get("mass_kg"), "qty": it["qty"]}
            if p["place"] == "frame":
                frame.append(rec)
                continue
            if p["place"] != "internal":
                external.append({**rec, "mass_kg": (it.get("mass_kg") or 0.0) * it["qty"]})
                continue
            if it.get("placeholder"):
                warnings.append(f"{it['name']}: your own payload is sent as a {it['dims_mm']} mm block (placeholder)")
            for k in range(int(it["qty"])):
                sent.append({**rec, "unit": k + 1})
    if not sent:
        raise SendError("the design has no parts inside the structure to pack")
    unplaceable = []
    for s in sent:
        if s["catalog_id"] == "user-payload" or s.get("unit", 1) > 1:
            continue
        g = cad.entry(s["catalog_id"])
        dims = tuple(g["extents_mm"]) if g else K.dims_mm(K.by_id(s["catalog_id"]))
        if S.packing_fit(dims, size) == "too_big":
            unplaceable.append(f"{s['name']} ({' × '.join(f'{x:g}' for x in dims)} mm)")
    if unplaceable:
        raise SendError(f"the optimiser cannot place {', '.join(unplaceable)} in a {FORM[size]}: it keeps every part "
                        "strictly inside the rail envelope. Choose a larger size in the Trade Study, another part, "
                        "or import the maker's CAD if its true outline is smaller.")
    name = project_name(design, root)
    store = ProjectStore(name, root=root)
    store.settings["form_factor"] = FORM[size]
    env = (design.get("requirements", {}).get("launch.environment") or {}).get("value")
    store.settings["launch_environment"] = env if env in LAUNCH else "gevs"
    store.settings["target_com_mm"] = [0.0, 0.0, 0.0]
    import trimesh
    for s in sent:
        cid = s["catalog_id"]
        if cid == "user-payload":
            dims = next(it["dims_mm"] for p in analysis["picks"].values() for it in p["items"]
                        if it["id"] == "user-payload")
            data = trimesh.creation.box(extents=dims).export(file_type="stl")
            s["origin"] = "placeholder"
        else:
            g = cad.geometry(cid)
            s["origin"] = g["origin"]
            data = (cad.root / g["file"]).read_bytes()
        label = re.sub(r"\s+", " ", s["name"]) + (f" ({s['unit']})" if s["qty"] > 1 else "")
        e = store.add_file(data, f"{cid}{'_' + str(s['unit']) if s['qty'] > 1 else ''}.stl", units="mm",
                           source="builder")
        e.name = label[:80]
        e.mass_override_kg = s["mass_kg"]
        e.subsystem_override = SUBSYSTEM.get(s["category"], "unknown")
        e.tags, e.tags_user = [], True                  # no automatic PC/104-stack tag: modules are free parts
        s["part_id"] = e.id
        if s["mass_kg"] is None:
            warnings.append(f"{s['name']}: no published mass — the optimiser uses its default density (ASSUMED)")
        fit = S.packing_fit(K.dims_mm(K.by_id(cid)) if K.by_id(cid) else None, size)
        if fit == "stage1":
            warnings.append(f"{s['name']}: fits the optimiser's idealized Stage 1 (the rail envelope) but not its "
                            "Stage 2 frame model (2 mm walls, 8.5 mm corner rails, 1.2 mm clearances)")
        elif fit == "too_big":
            warnings.append(f"{s['name']}: larger than the {FORM[size]} envelope: the optimiser cannot place it")
    store.save()
    sent_info = {
        "design_id": design["id"], "design_name": design.get("name"), "design_version": design.get("version"),
        "inputs_hash": analysis.get("inputs_hash"), "sent_at": now_iso(), "size": FORM[size],
        "parts": [{k: s[k] for k in ("part_id", "name", "catalog_id", "slot", "category", "origin", "mass_kg", "unit")}
                  for s in sent],
        "not_packed": external, "frame": frame, "warnings": warnings,
        "unenforced": unenforced(analysis, sent, external, frame),
        "disclaimer": analysis.get("disclaimer"),
    }
    atomic_write_text(store.folder / "builder.json", json.dumps(sent_info, indent=1))
    return {"project": name, **sent_info}
