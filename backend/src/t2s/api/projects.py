"""V3: the optimiser's projects — list them and switch the running app to another one.

A switch stops the coordinator of the current project and starts one on the chosen project, with the same worker
settings; open pages are told (WebSocket close code 4001) and reload onto it. Nothing in either project is changed or
deleted, so switching back restores the earlier project as it was saved.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re

from fastapi import APIRouter, HTTPException, Request

from ..service.coordinator import Coordinator
from ..service.project import ProjectStore

router = APIRouter(prefix="/api/projects")
SWITCHED = 4001
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_LOCK = asyncio.Lock()


def _root(app):
    return app.state.coord.store.folder.parent


def list_projects(app) -> list[dict]:
    root, current = _root(app), app.state.coord.store.name
    out = []
    for p in sorted(root.iterdir()) if root.is_dir() else []:
        f = p / "project.json"
        if not f.is_file():
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        b = p / "builder.json"
        builder = None
        if b.is_file():
            try:
                bj = json.loads(b.read_text(encoding="utf-8"))
                keep = ("design_id", "design_name", "design_version", "sent_at", "size", "parts", "not_packed",
                        "warnings", "unenforced")
                builder = {k: bj.get(k) for k in keep}
            except (OSError, json.JSONDecodeError):
                builder = None
        out.append({"name": p.name, "parts": len(d.get("parts", [])),
                    "form_factor": (d.get("settings") or {}).get("form_factor", "3U"),
                    "current": p.name == current, "builder": builder, "modified": f.stat().st_mtime})
    return out


async def switch_to(app, name: str) -> dict:
    """Run the app on project `name` (KeyError when there is no such project)."""
    if not _NAME.match(name):
        raise KeyError(name)
    async with _LOCK:
        old: Coordinator = app.state.coord
        root = old.store.folder.parent
        if not (root / name / "project.json").is_file():
            raise KeyError(name)
        if old.store.name == name:
            return {"project": name, "switched": False}
        clients = list(old.clients)
        kwargs = {"n_islands": old.n_islands, "n_validators": old.n_validators, "auto_start": old.auto_start,
                  "seed": old.seed, "workers": old.use_workers}
        await old.stop()
        new = Coordinator(ProjectStore(name, root=root), **kwargs)
        for attr in ("cpsat_time_s", "use_cpsat", "auto_ladder"):
            setattr(new, attr, getattr(old, attr))
        try:
            await new.start()
        except Exception:
            back = Coordinator(ProjectStore(old.store.name, root=root), **kwargs)
            await back.start()
            app.state.coord = back
            raise
        app.state.coord = new
        for cl in clients:
            with contextlib.suppress(Exception):               # a page that already left
                await cl.ws.close(code=SWITCHED, reason="project switched")
        return {"project": name, "switched": True, "previous": old.store.name}


@router.get("")
async def projects(request: Request):
    return {"projects": list_projects(request.app), "current": request.app.state.coord.store.name}


@router.post("/switch")
async def switch(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    name = str((body or {}).get("name") or "")
    try:
        return await switch_to(request.app, name)
    except KeyError as exc:
        raise HTTPException(404, f"no project {name}") from exc
