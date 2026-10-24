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

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..service.coordinator import VERSION, Client, Coordinator, InvalidSetting, jsonable
from ..service.project import REPO, ProjectStore

CHECKER = REPO / "tools" / "check_certificate.py"
FRONTEND_DIST = REPO / "frontend" / "dist"


class JSON(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(jsonable(content), allow_nan=False, separators=(",", ":")).encode("utf-8")


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

    @app.get("/api/debug/state")
    async def debug_state(request: Request):
        c = C(request)
        return {"run_status": c.run_status, "detail": c.status_detail, "ctx": c.ctx.ctx_id if c.ctx else None,
                "stage": c.ctx.stage if c.ctx else None, "stage2_mode": c.ctx.stage2_mode if c.ctx else None,
                "val_queue": [{"kind": x["kind"], "key": x["key"]} for x in c.val_queue],
                "val_pending": len(c.val_pending), "best_id": c.best_id, "least_id": c.least_id,
                "errors": c.errors[-8:],
                "workers": [{"id": w.id, "role": w.role, "ready": w.ready, "busy": w.busy, "ctx_ok": c.ctx is not None
                             and w.ctx_id == c.ctx.ctx_id, "info": w.info, "evals": w.evaluations} for w in c.workers]}

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
        try:
            c.apply_settings(await request.json())
        except InvalidSetting as exc:
            raise HTTPException(400, str(exc)) from exc
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
        items = c.layout_list(status, max(0, limit), current)     # also the layouts kept on disk only
        return {"layouts": [c.layout_json(e, full=False) for e in items], "best_id": c.best_id}

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
    async def ideamap(request: Request):
        return C(request).ideamap()

    @app.get("/api/pareto")
    async def pareto(request: Request):
        return C(request).pareto()

    @app.get("/api/stage2/attribution")
    async def attribution(request: Request):
        a = C(request).attribution()
        if a is None:
            raise HTTPException(404, "constraint attribution has not been run (POST /api/stage2/attribution/run)")
        return a

    @app.post("/api/stage2/attribution/run")
    async def attribution_run(request: Request):
        try:
            return C(request).start_attribution()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    # ------------------------------------------------------------------------------- V2 brackets
    @app.get("/api/gd/contest")
    async def gd_contest(request: Request):
        c = C(request).gd_contest()
        if c is None:
            raise HTTPException(404, "no generative-design contest results (run scripts/gd_contest.py)")
        return c

    @app.get("/api/studies/largest-size")
    async def largest_size(request: Request):
        r = C(request).largest_size()
        if r is None:
            raise HTTPException(404, "the largest-size search has not been run (POST /api/studies/largest-size/run)")
        return r

    @app.post("/api/studies/largest-size/run")
    async def largest_size_run(request: Request):
        try:
            return C(request).start_largest_size()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/layouts/{layout_id}/design-brackets")
    async def design_brackets(layout_id: str, request: Request):
        """Design the layout's brackets; body (optional) {pids: [part ids] to redesign only those, overrides:
        {part id: {material, vol_frac, min_member_mm}}} (V2 per-bracket settings, "auto" for the run to choose)."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        body = body if isinstance(body, dict) else {}
        try:
            return C(request).start_bracket_design(layout_id, body.get("pids"), body.get("overrides"))
        except KeyError as exc:
            raise HTTPException(404, f"unknown layout {layout_id}") from exc
        except InvalidSetting as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    # ------------------------------------------------------------------------------- M4 bracket layouts
    @app.get("/api/layouts/{layout_id}/bracket-layouts")
    async def bracket_layouts(layout_id: str, request: Request):
        """M4: the layout's three bracket layouts side by side (one per part, combined per wall, one piece)."""
        try:
            return C(request).bracket_layouts(layout_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown layout {layout_id}") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/layouts/{layout_id}/bracket-layouts/one_piece/estimate")
    async def one_piece_estimate(layout_id: str, request: Request):
        """M4: the one piece's grid, size and predicted time and memory before it is started; body {settings}."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        body = body if isinstance(body, dict) else {}
        try:
            return await asyncio.to_thread(C(request).one_piece_estimate, layout_id, body.get("settings"))
        except KeyError as exc:
            raise HTTPException(404, f"unknown layout {layout_id}") from exc
        except InvalidSetting as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/layouts/{layout_id}/bracket-layouts/{mode}/run")
    async def bracket_layout_run(layout_id: str, mode: str, request: Request):
        """M4: design the layout's combined brackets or its one piece in the background; body {settings: {material,
        vol_frac, min_member_mm, budget_s}, overrides: {group key: settings}} (all optional)."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        body = body if isinstance(body, dict) else {}
        try:
            return C(request).start_bracket_layout(layout_id, mode, body.get("settings"), body.get("overrides"))
        except KeyError as exc:
            raise HTTPException(404, f"unknown layout {layout_id}") from exc
        except InvalidSetting as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/layouts/{layout_id}/bracket-layouts/use")
    async def bracket_layout_use(layout_id: str, request: Request):
        """M4: choose the bracket layout the layout is shown and saved with; body {mode}."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        mode = (body or {}).get("mode") if isinstance(body, dict) else None
        try:
            return C(request).use_bracket_layout(layout_id, str(mode))
        except KeyError as exc:
            raise HTTPException(404, f"unknown layout {layout_id}") from exc
        except InvalidSetting as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/design-options")
    async def design_options(request: Request):
        """V2: what the bracket designs can be set to — launch environments, AM materials, the ranges of the
        per-bracket settings — and the project's current choices."""
        return C(request).design_options()

    @app.get("/api/saved-stl")
    async def saved_stl(request: Request):
        """V2: the saved STL files of the designed best layout (manifest, folder, a save under way)."""
        return C(request).saved_stl()

    @app.post("/api/saved-stl")
    async def save_stl(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        c = C(request)
        lid = (body or {}).get("layout_id") or c.best_id
        if not lid:
            raise HTTPException(409, "no layout to save")
        try:
            return c.save_stl(lid)
        except KeyError as exc:
            raise HTTPException(404, f"unknown layout {lid}") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/saved-stl/download")
    async def saved_stl_download(request: Request):
        try:
            data = await asyncio.to_thread(C(request).saved_stl_zip)
        except KeyError as exc:
            raise HTTPException(404, "no saved STL files yet") from exc
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="saved_stl.zip"'})

    # ------------------------------------------------------------------------------------------- studies
    @app.get("/api/benchmarks")
    async def benchmarks(request: Request, instance: str | None = None, preset: str | None = None):
        b = await asyncio.to_thread(C(request).benchmarks, instance, preset)
        if b is None:
            raise HTTPException(404, "no benchmark results yet (POST /api/benchmarks/run)")
        return b

    @app.post("/api/benchmarks/run")
    async def benchmarks_run(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            return C(request).start_benchmarks(body or {})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/benchmarks/stop")
    async def benchmarks_stop(request: Request):
        return {"stopped": C(request).stop_study("benchmark")}

    @app.get("/api/studies/size")
    async def size_study(request: Request):
        s = C(request).size_study()
        if s is None:
            raise HTTPException(404, "the Size Study has not been run for these parts (POST /api/studies/size/run)")
        return s

    @app.post("/api/studies/size/run")
    async def size_study_run(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            return C(request).start_size_study(body or {})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/studies/size/stop")
    async def size_study_stop(request: Request):
        return {"stopped": C(request).stop_study("size")}

    @app.get("/api/experiments/free-rotation")
    async def free_rotation(request: Request):
        r = C(request).free_rotation()
        if r is None:
            raise HTTPException(404, "the free-rotation experiment has not been run for these parts "
                                     "(POST /api/experiments/free-rotation/run)")
        return r

    @app.post("/api/experiments/free-rotation/run")
    async def free_rotation_run(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            return C(request).start_free_rotation(body or {})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/mfg")
    async def mfg(request: Request):
        r = C(request).mfg()
        if r is None:
            raise HTTPException(404, "Manufacturable Design has not been run for these parts (POST /api/mfg/run)")
        return r

    @app.post("/api/mfg/run")
    async def mfg_run(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            return C(request).start_mfg(body or {})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/mfg/download/{name}")
    async def mfg_download(request: Request, name: str):
        try:
            p = C(request).mfg_file(name)
        except KeyError as exc:
            raise HTTPException(404, f"no export {name}") from exc
        media = "text/csv" if p.suffix == ".csv" else "model/stl"
        return FileResponse(p, media_type=media, filename=p.name)

    @app.get("/api/items/{iid}/mesh")
    async def item_mesh(request: Request, iid: str):
        try:
            return Response(C(request).item_mesh(iid), media_type="application/octet-stream")
        except KeyError as exc:
            raise HTTPException(404, f"no item {iid}") from exc

    # ------------------------------------------------------------------------------------------- CAD / export
    @app.get("/api/cad/status")
    async def cad_status():
        return {"status": "NOT_CONFIGURED",
                "detail": "FUSION 360 VALIDATION: NOT CONFIGURED. Autodesk Fusion 360 is not installed or configured; "
                          "no Fusion 360 API calls are made until you confirm the integration is ready."}

    async def _report(c: Coordinator, e) -> tuple[list, dict | None]:
        from ..report.build import report_blocks
        proof, err = None, None
        try:
            proof = await asyncio.to_thread(c.build_proof, e.id)
        except (ValueError, KeyError) as exc:
            err = str(exc)
        return report_blocks(c, e, VERSION, proof, err), proof

    @app.post("/api/cad/package/{lid}")
    async def cad_package(request: Request, lid: str):
        """Prepares the Fusion 360 export package (no Fusion 360 call is made: NOT CONFIGURED)."""
        from ..report.build import FUSION_STATUS, fusion_package, render_markdown
        c = C(request)
        e = layout_or_404(c, lid)
        if e.status not in ("VALIDATED", "FINAL") or not c._current(e):
            raise HTTPException(409, f"only a VALIDATED or FINAL layout for the current inputs can be packaged "
                                     f"({lid} is {e.status}{'' if c._current(e) else ', inputs changed'})")
        blocks, proof = await _report(c, e)
        data = await asyncio.to_thread(fusion_package, c, e, VERSION, render_markdown(blocks), proof, CHECKER)
        out = c.store.folder / "exports" / f"fusion_package_{lid}.zip"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return {"status": "PACKAGED", "fusion360": "NOT_CONFIGURED", "detail": f"{FUSION_STATUS}: package prepared, "
                "nothing was checked in Fusion 360", "path": str(out), "bytes": len(data),
                "download": f"/api/cad/package/{lid}/download"}

    @app.get("/api/cad/package/{lid}/download")
    async def cad_package_download(request: Request, lid: str):
        c = C(request)
        p = c.store.folder / "exports" / f"fusion_package_{lid}.zip"
        if lid not in c.archive or not p.is_file():
            raise HTTPException(404, f"no Fusion export package for {lid} (POST /api/cad/package/{lid})")
        return FileResponse(p, media_type="application/zip", filename=p.name)

    @app.get("/api/layouts/{lid}/bom")
    async def layout_bom(request: Request, lid: str, format: str = "json"):
        """V2: the layout's bill of materials (report/bom.py); format=csv downloads it."""
        from ..report.bom import bom, bom_csv
        c = C(request)
        e = layout_or_404(c, lid)
        if format not in ("json", "csv"):
            raise HTTPException(400, "format must be json or csv")
        b = bom(c, e)
        if format == "csv":
            return Response(bom_csv(b), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="bom_{lid}.csv"'})
        return b

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
            wr.writerow(["part_id", "name", "orient", "x_mm", "y_mm", "z_mm", "mass_kg", "mass_source", "part_scale"])
            for p in lj["poses"]:
                rec = c.rec_at(p["part_id"], e.part_scale)
                wr.writerow([p["part_id"], rec.name if rec else "", p["orient"], *[v / 1000 for v in p["t_um"]],
                             rec.mass_kg if rec else "", rec.mass_source if rec else "", e.part_scale])
            return Response(buf.getvalue(), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="layout_{lid}.csv"'})
        from ..report.build import render_html, render_markdown, stl_zip
        if kind in ("report_md", "report_html"):
            blocks, _ = await _report(c, e)
            if kind == "report_md":
                return Response(render_markdown(blocks), media_type="text/markdown",
                                headers={"Content-Disposition": f'attachment; filename="report_{lid}.md"'})
            return Response(render_html(blocks, f"Layout report {lid}"), media_type="text/html",
                            headers={"Content-Disposition": f'attachment; filename="report_{lid}.html"'})
        if kind == "stl_zip":
            data = await asyncio.to_thread(stl_zip, c, e, VERSION)
            return Response(data, media_type="application/zip",
                            headers={"Content-Disposition": f'attachment; filename="layout_{lid}_stl.zip"'})
        raise HTTPException(400, "kind must be json, csv, report_md, report_html or stl_zip")

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
                try:
                    c.apply_settings(p.get("settings") or {})
                except InvalidSetting as exc:               # nothing changed; the edit is still acknowledged
                    c.send(client, "error", {"message": f"settings refused: {exc}"})
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
