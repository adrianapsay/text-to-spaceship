"""CubeSat Builder REST endpoints (V3), mounted under /api/builder by api.app.create_app.

Designs are kept by the BuilderStore in data/builder (app.state.builder) and CAD in data/builder/cad. Only Send to
Optimization touches the optimiser: it writes a new project (never overwriting one) and may switch the app to it.
"""
from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..builder import catalog, engine, questions, regions
from ..builder import recommend as rc
from ..builder.analysis import refs
from ..builder.analysis import structure as st
from ..builder.cad import ORIGINS, CadError, CadStore
from ..builder.intake import apply_statement
from ..builder.model import new_design, touch
from ..builder.send import SendError, send
from ..builder.store import BuilderStore
from .projects import switch_to

router = APIRouter(prefix="/api/builder")


def _store(request: Request) -> BuilderStore:
    return request.app.state.builder


def _cad(request: Request) -> CadStore:
    """The CAD files next to the designs (data/builder/cad; git-ignored)."""
    st = request.app.state
    if getattr(st, "builder_cad", None) is None:
        st.builder_cad = CadStore(_store(request).root / "cad")
    return st.builder_cad


def _load(request: Request, did: str) -> dict:
    try:
        return _store(request).load(did)
    except KeyError as exc:
        raise HTTPException(404, f"no Builder design {did}") from exc


def _expert(request: Request) -> bool:
    return request.query_params.get("expert") in ("1", "true", "yes")


def view(design: dict, expert: bool = False) -> dict:
    """The questionnaire state of a design: the next question, what is still open, the requirements set so far
    (with where each value came from) and how complete the answers are."""
    todo = questions.pending(design, expert)
    reqs = []
    for q in questions.applicable(design):
        r = design["requirements"].get(q.key)
        if r is not None:
            reqs.append({"key": q.key, "qid": q.id, "section": q.section, "prompt": q.prompt, **r,
                         "display": questions.display(q, r["value"]),
                         "answer_why": (design["answers"].get(q.id) or {}).get("why")})
    return {"next": questions.describe(todo[0], design) if todo else None,
            "pending": [q.id for q in todo], "completeness": questions.completeness(design, expert),
            "requirements": reqs, "sections": questions.SECTIONS}


def short_name(statement: str, n: int = 60) -> str:
    """A design's name from its statement: whole words, at most n characters, "…" when cut."""
    s = " ".join(statement.split()).rstrip(".")
    if len(s) <= n:
        return s or "New mission"
    cut = s[:n].rsplit(" ", 1)[0]
    return (cut or s[:n]) + "…"


def _out(design: dict, expert: bool, **extra) -> dict:
    return {"design": design, "view": view(design, expert), **extra}


@router.get("/meta")
async def meta():
    return {"regions": [regions.region(k) for k in regions.REGIONS],
            "stations": [regions.station(k) for k in regions.STATIONS],
            "sections": questions.SECTIONS,
            "questions": len(questions.QUESTIONS),
            "sliders": rc.SLIDERS, "sizes": list(st.SIZES), "packed_sizes": list(st.PACKED_SIZES),
            "slots": [{"id": s.id, "label": s.label, "categories": list(s.categories), "place": s.place}
                      for s in rc.SLOTS],
            "categories": catalog.CATEGORIES, "engine": engine.ENGINE_VERSION}


@router.get("/designs")
async def list_designs(request: Request):
    return {"designs": _store(request).list()}


@router.post("/designs")
async def create_design(request: Request):
    body = await _body(request)
    d = new_design(str(body.get("name") or ""), "")
    found = []
    if body.get("statement"):
        d, found = apply_statement(d, str(body["statement"]))
        if not body.get("name"):
            d["name"] = short_name(str(body["statement"]))
    _store(request).save(d)
    return _out(d, _expert(request), findings=found)


@router.get("/designs/{did}")
async def get_design(request: Request, did: str):
    return _out(_load(request, did), _expert(request))


@router.patch("/designs/{did}")
async def rename_design(request: Request, did: str):
    d = _load(request, did)
    body = await _body(request)
    if "name" in body:
        name = str(body["name"]).strip()
        if not name:
            raise HTTPException(400, "a design needs a name")
        d["name"] = name[:120]
        touch(d, "renamed")
    _store(request).save(d)
    return _out(d, _expert(request))


@router.post("/designs/{did}/statement")
async def statement(request: Request, did: str):
    d = _load(request, did)
    body = await _body(request)
    d, found = apply_statement(d, str(body.get("text") or ""))
    _store(request).save(d)
    return _out(d, _expert(request), findings=found)


@router.post("/designs/{did}/answer")
async def answer(request: Request, did: str):
    d = _load(request, did)
    body = await _body(request)
    try:
        questions.answer(d, str(body.get("qid")), body.get("value"), unknown=bool(body.get("unknown")))
    except KeyError as exc:
        raise HTTPException(404, f"no question {body.get('qid')}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _store(request).save(d)
    return _out(d, _expert(request))


@router.delete("/designs/{did}/answer/{qid}")
async def unanswer(request: Request, did: str, qid: str):
    d = _load(request, did)
    questions.unanswer(d, qid)
    _store(request).save(d)
    return _out(d, _expert(request))


@router.post("/designs/{did}/defaults")
async def defaults(request: Request, did: str):
    d = _load(request, did)
    questions.accept_defaults(d, _expert(request))
    _store(request).save(d)
    return _out(d, _expert(request))


@router.get("/designs/{did}/questions")
async def all_questions(request: Request, did: str):
    """Every applicable question with its current answer (the requirements editor)."""
    d = _load(request, did)
    ex = _expert(request)
    return {"questions": [questions.describe(q, d) for q in questions.applicable(d) if ex or not q.advanced],
            "view": view(d, ex)}


# ============================================================================================ analysis (M2/M3)
@router.get("/designs/{did}/analysis")
async def analysis(request: Request, did: str):
    """The architecture, calculations, budgets and checks of the design as it is now (computed off the event loop;
    cached by the design's inputs). `design_version` says which version of the design it describes."""
    d = _load(request, did)
    a = await asyncio.to_thread(engine.analyse, d)
    manifest = _cad(request).manifest()
    used = {i["id"] for p in a["picks"].values() for i in p["items"]}
    return {**a, "geometry": {cid: {k: manifest[cid].get(k) for k in ("origin", "origin_text", "ok", "extents_mm")}
                              for cid in used if cid in manifest}}


@router.post("/designs/{did}/selection")
async def select(request: Request, did: str):
    """Choose a part for a slot ({slot, component, qty}); component null removes the slot's part."""
    d = _load(request, did)
    body = await _body(request)
    slot = str(body.get("slot") or "")
    if slot not in rc.SLOT:
        raise HTTPException(404, f"no slot {slot}")
    cid = body.get("component")
    if cid is not None:
        c = catalog.by_id(str(cid))
        if c is None:
            raise HTTPException(404, f"no catalog entry {cid}")
        if c["category"] not in rc.SLOT[slot].categories:
            raise HTTPException(400, f"{c['product']} is a {catalog.CATEGORIES[c['category']].lower()}, not a "
                                     f"{rc.SLOT[slot].label.lower()}")
    try:
        qty = max(1, min(int(body.get("qty") or 1), 12))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "qty is a whole number") from exc
    d.setdefault("selections", {})[slot] = {"component": cid, "qty": qty}
    touch(d, f"{slot}: {'removed' if cid is None else cid}")
    _store(request).save(d)
    return _out(d, _expert(request))


@router.delete("/designs/{did}/selection/{slot}")
async def unselect(request: Request, did: str, slot: str):
    """Hand a slot back to the architect's recommendation."""
    d = _load(request, did)
    if (d.get("selections") or {}).pop(slot, None) is not None:
        touch(d, f"{slot}: back to the recommendation")
        _store(request).save(d)
    return _out(d, _expert(request))


@router.patch("/designs/{did}/prefs")
async def prefs(request: Request, did: str):
    """Set the trade sliders (0 … 1 each), the lifetime override (years or null) and the CubeSat size (or null)."""
    d = _load(request, did)
    body = await _body(request)
    p = dict(d.get("prefs") or {})
    for k in rc.SLIDERS:
        if k in body:
            try:
                p[k] = min(1.0, max(0.0, float(body[k])))
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, f"{k} is a number from 0 to 1") from exc
    if "lifetime_years" in body:
        v = body["lifetime_years"]
        if v is None:
            p.pop("lifetime_years", None)
        else:
            try:
                p["lifetime_years"] = min(15.0, max(0.1, float(v)))
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "lifetime_years is a number of years") from exc
    if "size_u" in body:
        v = body["size_u"]
        if v is None:
            d.pop("size_u", None)
        elif v in st.SIZES or (isinstance(v, (int, float)) and float(v) in [float(s) for s in st.SIZES]):
            d["size_u"] = next(s for s in st.SIZES if float(s) == float(v))
        else:
            raise HTTPException(400, f"size_u is one of {', '.join(f'{s:g}' for s in st.SIZES)}")
    d["prefs"] = p
    touch(d, "trade settings")
    _store(request).save(d)
    return _out(d, _expert(request))


@router.get("/catalog")
async def catalog_list(request: Request):
    """The component catalog (summaries), optionally one category (?category=camera)."""
    cat = request.query_params.get("category")
    items = catalog.by_category(cat) if cat else catalog.components()
    return {"categories": catalog.CATEGORIES, "components": [catalog.summary(c) for c in items],
            "refs": {k: refs.ref(k) for k in refs.REFS}}


@router.post("/designs/{did}/send")
async def send_to_optimization(request: Request, did: str):
    """Send the design as it is now to the optimiser: a new project builder-<mission>[-n] (never overwriting one);
    with {"switch": true} the app then runs on it (open pages reload)."""
    d = _load(request, did)
    body = await _body(request)
    coord = getattr(request.app.state, "coord", None)
    if coord is None:
        raise HTTPException(503, "the optimiser is not running in this app")
    a = await asyncio.to_thread(engine.analyse, d)
    root = coord.store.folder.parent
    try:
        out = await asyncio.to_thread(send, d, a, _cad(request), root)
    except SendError as exc:
        raise HTTPException(400, str(exc)) from exc
    d.setdefault("sent", []).append({"project": out["project"], "at": out["sent_at"], "version": d.get("version")})
    touch(d, f"sent to the optimiser as {out['project']}")
    _store(request).save(d)
    out["switched"] = False
    if body.get("switch"):
        sw = await switch_to(request.app, out["project"])
        out["switched"] = sw.get("switched", False)
        out["previous"] = sw.get("previous")
    return out


@router.get("/cad")
async def cad_list(request: Request):
    """The CAD geometry of each part (origin, checks), and the CAD each maker offers publicly (links only: the app
    never downloads; the user downloads and imports)."""
    offered = []
    for c in catalog.components():
        cad = c.get("cad") or {}
        if cad.get("available") in ("public", "registration", "on request"):
            offered.append({"id": c["id"], "name": f"{c['manufacturer']} {c['product']}",
                            "available": cad["available"], "url": cad.get("url"), "formats": cad.get("formats") or [],
                            "note": cad.get("note")})
    return {"origins": ORIGINS, "items": _cad(request).manifest(), "offered": offered}


@router.post("/cad/{cid}/import")
async def cad_import(request: Request, cid: str, file: Annotated[UploadFile, File()],
                     origin: Annotated[str, Form()] = "manufacturer",
                     source_url: Annotated[str | None, Form()] = None):
    """Import the user's CAD file for a part: STEP (preferred), IGES, BREP, STL, or a .zip of one."""
    data = await file.read()
    try:
        return await asyncio.to_thread(_cad(request).import_file, cid, file.filename or "part", data, origin,
                                       source_url)
    except KeyError as exc:
        raise HTTPException(404, f"no catalog entry {cid}") from exc
    except CadError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/cad/{cid}/simplified")
async def cad_simplified(request: Request, cid: str):
    """A simplified bounding box of the part's published size (a placeholder cube when none is published)."""
    try:
        return await asyncio.to_thread(_cad(request).simplified, cid)
    except KeyError as exc:
        raise HTTPException(404, f"no catalog entry {cid}") from exc


@router.delete("/cad/{cid}")
async def cad_delete(request: Request, cid: str):
    try:
        _cad(request).delete(cid)
    except KeyError as exc:
        raise HTTPException(404, f"no catalog entry {cid}") from exc
    return {"ok": True}


@router.get("/cad/{cid}/stl")
async def cad_stl(request: Request, cid: str):
    try:
        p = _cad(request).stl_path(cid)
    except KeyError as exc:
        raise HTTPException(404, f"no geometry for {cid}") from exc
    if not p.is_file():
        raise HTTPException(404, f"no geometry for {cid}")
    return FileResponse(p, media_type="model/stl", filename=p.name)


@router.get("/catalog/{cid}")
async def catalog_entry(cid: str):
    c = catalog.by_id(cid)
    if c is None:
        raise HTTPException(404, f"no catalog entry {cid}")
    return {"component": {k: v for k, v in c.items() if not k.startswith("_")}, "summary": catalog.summary(c),
            "unpublished": rc.unpublished(c)}


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:  # noqa: BLE001 - an empty or invalid body is an empty one
        return {}
    return b if isinstance(b, dict) else {}
