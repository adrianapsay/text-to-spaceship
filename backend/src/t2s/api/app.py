"""FastAPI application: REST endpoints and the /ws WebSocket of docs/api-contract.md v1.

Bound to 127.0.0.1 only (run_server.py). Endpoints for features that are not built yet answer 501 with a plain
explanation, which the front end shows as an empty state.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..service.coordinator import VERSION, Client, Coordinator, jsonable
from ..service.project import REPO, ProjectStore

CHECKER = REPO / "tools" / "check_certificate.py"
FRONTEND_DIST = REPO / "frontend" / "dist"


class JSON(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(jsonable(content), allow_nan=False, separators=(",", ":")).encode("utf-8")


def not_built(what: str, milestone: str):
    return JSON({"status": "NOT_AVAILABLE", "detail": f"{what} is not built yet ({milestone})."}, status_code=501)


def create_app(coord: Coordinator | None = None, project: str = "default", **coord_kwargs) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = coord or Coordinator(ProjectStore(project), **coord_kwargs)
        app.state.coord = c
        await c.start()
        try:
            yield
        finally:
            await c.stop()

    app = FastAPI(title="TEXT-TO-SPACESHIP", version=VERSION, lifespan=lifespan, default_response_class=JSON)

    def C(request: Request) -> Coordinator:
        return request.app.state.coord

    def layout_or_404(c: Coordinator, lid: str):
        e = c.archive.get(lid)
        if e is None:
            raise HTTPException(404, f"no layout {lid}")
        return e

    # ------------------------------------------------------------------------------------------- basics
    @app.get("/api/health")
    async def health(request: Request):
        c = C(request)
        return {"ok": True, "version": VERSION, "ready": c.ready, "run_status": c.run_status,
                "evaluations": c.evaluations, "archive": len(c.archive), "best_id": c.best_id,
                "building": sum(1 for f in c.builds.values() if not f.done()),
                "workers": [{"id": w.id, "role": w.role, "ready": w.ready} for w in c.workers],
                "fusion360": "NOT_CONFIGURED"}

    @app.get("/api/project")
    async def project_snapshot(request: Request):
        return C(request).project_json()

    # ------------------------------------------------------------------------------------------- parts
    @app.post("/api/parts")
    async def add_parts(request: Request, files: list[UploadFile] = File(..., alias="files[]"),
                        units: str | None = Form(None)):
        c = C(request)
        payload = [(f.filename or "part.stl", await f.read()) for f in files]
        try:
            parts = c.add_files(payload, units)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"parts": parts}

    @app.post("/api/parts/{pid}/units")
    async def confirm_units(request: Request, pid: str):
        body = await request.json()
        try:
            return await C(request).confirm_units(pid, body.get("units"))
        except KeyError as exc:
            raise HTTPException(404, f"no part {pid}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.patch("/api/parts/{pid}")
    async def patch_part(request: Request, pid: str):
        body = await request.json()
        try:
            return C(request).apply_part_patch(pid, body)
        except KeyError as exc:
            raise HTTPException(404, f"no part {pid}") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/parts/{pid}")
    async def delete_part(request: Request, pid: str):
        try:
            C(request).remove_part(pid)
        except KeyError as exc:
            raise HTTPException(404, f"no part {pid}") from exc
        return {"ok": True}

    @app.get("/api/parts/{pid}/mesh")
    async def part_mesh(request: Request, pid: str, lod: str = "display"):
        try:
            data = C(request).mesh_bytes(pid)
        except KeyError as exc:
            raise HTTPException(404, f"no part {pid}") from exc
        return Response(data, media_type="application/octet-stream")

    @app.get("/api/parts/{pid}/proxy")
    async def part_proxy(request: Request, pid: str, level: str = "G1"):
        c = C(request)
        rec = c.records.get(pid)
        if rec is None:
            raise HTTPException(404, f"no analysed part {pid}")
        if level == "G1":
            return {"level": "G1", "boxes": rec.boxes.tolist(), "certified": rec.boxes_certified, "method": rec.boxes_method}
        if level in ("G2", "G3"):
            import numpy as np
            from scipy.spatial import ConvexHull
            sets = [rec.v[rec.hull.vertex_ids]] if level == "G2" else [p.vertices for p in rec.cover.pieces]
            hulls = []
            for pts in sets:
                try:
                    h = ConvexHull(pts)
                    hulls.append({"positions": np.asarray(pts, float).ravel().tolist(), "indices": h.simplices.ravel().tolist()})
                except Exception:  # noqa: BLE001
                    continue
            return {"level": level, "hulls": hulls, "certified": bool(rec.cover.certified) if level == "G3" else True}
        raise HTTPException(400, "level must be G1, G2 or G3")

    @app.get("/api/parts/{pid}/fidelity")
    async def part_fidelity(request: Request, pid: str):
        try:
            f = C(request).fidelity(pid)
        except KeyError as exc:
            raise HTTPException(404, f"no part {pid}") from exc
        if f is None:
            raise HTTPException(404, "the detail-level study has not been run for this part (POST /api/fidelity/run)")
        return f

    @app.post("/api/fidelity/run")
    async def fidelity_run(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        c = C(request)
        started = c.start_ladders(body.get("part_ids"), float(body.get("budget_s", 600.0)))
        return {"started": started, "queued_total": sum(1 for x in c.ladders.values() if not x["future"].done())}

    @app.get("/api/fidelity/summary")
    async def fidelity_summary(request: Request):
        return C(request).fidelity_summary()

    # ------------------------------------------------------------------------------------------- settings / run
    @app.put("/api/settings")
    async def put_settings(request: Request):
        c = C(request)
        c.apply_settings(await request.json())
        return c.store.settings

    @app.post("/api/run")
    async def run(request: Request):
        body = await request.json()
        try:
            C(request).run_control(body.get("action", ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_status": C(request).run_status}

    # ------------------------------------------------------------------------------------------- layouts
    @app.get("/api/layouts")
    async def layouts(request: Request, status: str | None = None, limit: int = 200, current: bool | None = None):
        c = C(request)
        items = list(c.archive.values())
        if status:
            items = [e for e in items if e.status == status]
        if current is not None:
            items = [e for e in items if c._current(e) == current]
        items.sort(key=lambda e: e.id, reverse=True)
        return {"layouts": [c.layout_json(e, full=False) for e in items[:limit]], "best_id": c.best_id}

    @app.get("/api/layouts/{lid}")
    async def layout(request: Request, lid: str):
        c = C(request)
        return c.layout_json(layout_or_404(c, lid))

    @app.post("/api/layouts/{lid}/final")
    async def finalize(request: Request, lid: str):
        c = C(request)
        layout_or_404(c, lid)
        try:
            return await asyncio.to_thread(c.finalize, lid)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/layouts/{lid}/proof")
    async def proof(request: Request, lid: str):
        c = C(request)
        layout_or_404(c, lid)
        try:
            p = await asyncio.to_thread(c.build_proof, lid)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"markdown": p["markdown"], "certificate": p["certificate"], "valid": p["valid"]}

    @app.get("/api/layouts/{lid}/proof/download")
    async def proof_download(request: Request, lid: str, kind: str = "md"):
        c = C(request)
        layout_or_404(c, lid)
        if kind == "checker":
            return FileResponse(CHECKER, media_type="text/x-python", filename="check_certificate.py")
        try:
            p = await asyncio.to_thread(c.build_proof, lid)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if kind == "md":
            return Response(p["markdown"], media_type="text/markdown",
                            headers={"Content-Disposition": f'attachment; filename="proof_{lid}.md"'})
        if kind == "json":
            return Response(json.dumps(p["certificate"], indent=1), media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="certificate_{lid}.json"'})
        raise HTTPException(400, "kind must be md, json or checker")

    # ------------------------------------------------------------------------------------------- explain / selector
    @app.get("/api/selector")
    async def selector(request: Request):
        return C(request).selector()

    @app.get("/api/selector/sweep")
    async def selector_sweep(request: Request, slider: str = "space"):
        c = C(request)
        if c.ctx is None:
            raise HTTPException(409, "no packable parts yet")
        try:
            return c.selector_sweep(slider)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/selector/map")
    async def selector_map(request: Request, x: str = "space", y: str = "balance", n: int = 41):
        c = C(request)
        if c.ctx is None:
            raise HTTPException(409, "no packable parts yet")
        try:
            return c.selector_map(x, y, n)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/ideamap")
    async def ideamap():
        return not_built("The idea map", "M8")

    @app.get("/api/pareto")
    async def pareto(request: Request):
        return C(request).pareto()

    # ------------------------------------------------------------------------------------------- studies
    @app.get("/api/benchmarks")
    async def benchmarks():
        return {"status": "NOT_RUN", "detail": "Benchmarks arrive with M8."}

    @app.post("/api/benchmarks/run")
    async def benchmarks_run():
        return not_built("Benchmarks", "M8")

    @app.get("/api/studies/size")
    async def size_study():
        return {"status": "NOT_RUN", "detail": "The Size Study arrives with M8."}

    @app.post("/api/studies/size/run")
    async def size_study_run():
        return not_built("The Size Study", "M8")

    @app.get("/api/mfg")
    async def mfg():
        return {"status": "NOT_RUN", "detail": "Manufacturable Design arrives with M9."}

    @app.post("/api/mfg/run")
    async def mfg_run():
        return not_built("Manufacturable Design", "M9")

    @app.get("/api/items/{iid}/mesh")
    async def item_mesh(iid: str):
        raise HTTPException(404, f"no item {iid}")

    # ------------------------------------------------------------------------------------------- CAD / export
    @app.get("/api/cad/status")
    async def cad_status():
        return {"status": "NOT_CONFIGURED",
                "detail": "FUSION 360 VALIDATION: NOT CONFIGURED. Autodesk Fusion 360 is not installed or configured; "
                          "no Fusion 360 API calls are made until you confirm the integration is ready."}

    @app.post("/api/cad/package/{lid}")
    async def cad_package(lid: str):
        return not_built("The Fusion 360 export package", "M10")

    @app.get("/api/export/{lid}")
    async def export(request: Request, lid: str, kind: str = "json"):
        c = C(request)
        e = layout_or_404(c, lid)
        lj = c.layout_json(e)
        if kind == "json":
            return Response(json.dumps(lj, indent=1), media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="layout_{lid}.json"'})
        if kind == "csv":
            buf = io.StringIO()
            wr = csv.writer(buf)
            wr.writerow(["part_id", "name", "orient", "x_mm", "y_mm", "z_mm", "mass_kg", "mass_source"])
            for p in lj["poses"]:
                rec = c.records.get(p["part_id"])
                wr.writerow([p["part_id"], rec.name if rec else "", p["orient"], *[v / 1000 for v in p["t_um"]],
                             rec.mass_kg if rec else "", rec.mass_source if rec else ""])
            return Response(buf.getvalue(), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="layout_{lid}.csv"'})
        return not_built(f"Export kind '{kind}'", "M10")

    # ------------------------------------------------------------------------------------------- WebSocket
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        c: Coordinator = ws.app.state.coord
        client = Client(ws)
        c.clients.add(client)

        async def sender():
            while True:
                msg = await client.queue.get()
                await ws.send_text(msg)

        task = asyncio.create_task(sender())
        try:
            while True:
                text = await ws.receive_text()
                try:
                    env = json.loads(text)
                except json.JSONDecodeError:
                    c.send(client, "error", {"message": "malformed JSON"})
                    continue
                await handle(c, client, env)
        except WebSocketDisconnect:
            pass
        finally:
            c.clients.discard(client)
            task.cancel()

    async def handle(c: Coordinator, client: Client, env: dict) -> None:
        t = env.get("type")
        p = env.get("payload") or {}
        try:
            if t == "hello":
                client.want_candidates = bool(p.get("want_candidates", False))
                c.send(client, "state.snapshot", c.snapshot())
            elif t == "ping":
                c.send(client, "pong", {})
            elif t == "edit.settings":
                c.apply_settings(p.get("settings") or {})
                client.applied = max(client.applied, int(p.get("client_seq", 0)))
                c.send(client, "edit.ack", {"client_seq": client.applied})
            elif t == "edit.part":
                seq = int(p.get("client_seq", 0))
                try:
                    c.apply_part_patch(p.get("part_id"), p.get("patch") or {})
                except (KeyError, ValueError) as exc:
                    c.send(client, "error", {"message": f"edit of {p.get('part_id')} refused: {exc}"})
                client.applied = max(client.applied, seq)
                c.send(client, "edit.ack", {"client_seq": seq})
            elif t == "run.control":
                c.run_control(p.get("action", ""))
            else:
                c.send(client, "error", {"message": f"unknown message type {t!r}"})
        except Exception as exc:  # noqa: BLE001
            c.send(client, "error", {"message": f"{t} failed: {exc}"})

    # ------------------------------------------------------------------------------------------- static UI
    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return HTMLResponse((FRONTEND_DIST / "index.html").read_text(encoding="utf-8"))

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = (FRONTEND_DIST / path).resolve()
            if f.is_file() and FRONTEND_DIST.resolve() in f.parents:
                return FileResponse(f)
            if path.startswith(("api/", "ws")):
                raise HTTPException(404)
            return HTMLResponse((FRONTEND_DIST / "index.html").read_text(encoding="utf-8"))

    return app
