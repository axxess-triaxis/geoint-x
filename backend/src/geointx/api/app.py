"""HTTP API and static hosting for the dashboard."""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from geointx import evidence
from geointx.agent import loop as agent_loop
from geointx.agent.strategy import StrategyName
from geointx.ai import assistant
from geointx.ai.client import LlmClient, build_client
from geointx.ai.interpret import interpret
from geointx.ai.tools import NoArgs, Tools
from geointx.api import reports
from geointx.cases import workflow
from geointx.cases.audit import verify_chain
from geointx.geo.grid import GridSpec
from geointx.imagery import render
from geointx.imagery.pack import DemoPack
from geointx.imagery.release_fetch import fetch_rasters
from geointx.models import Finding, PriorityResult, Role
from geointx.services import (
    add_polygon,
    apply_case_action,
    event_dicts,
    grid_corners,
    run_detection_for_aoi,
    seed_from_pack,
)
from geointx.settings import Settings, get_settings
from geointx.store.db import (
    AiCacheRow,
    AoiRow,
    CaseEventRow,
    CaseRow,
    FindingRow,
    PolygonRow,
    RunRow,
    SchedulerDecisionRow,
    UploadBlobRow,
    make_engine,
)

log = logging.getLogger("geointx")

# Vercel caps request bodies at 4.5 MB.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024


class State:
    settings: Settings
    engine: Engine
    pack: DemoPack
    llm: LlmClient | None


STATE = State()

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _render_lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    STATE.settings = s
    STATE.engine = make_engine(s.database_url)
    STATE.pack = DemoPack(s.pack_dir, fetch_rasters if s.pack_autofetch else None)
    STATE.llm = build_client(s.gemini_api_key, s.gemini_model, s.gemini_timeout_s, s.ai_enabled)
    seed_from_pack(STATE.engine, STATE.pack)
    s.artifact_dir.mkdir(parents=True, exist_ok=True)
    s.upload_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="GEOINT-X", version="0.1.0")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Operators (and serverless deployments without log access) see what failed;
        # no traceback or request data is returned.
        log.exception("unhandled error")
        return JSONResponse(
            {"detail": "internal error", "error": f"{type(exc).__name__}: {exc}"[:400]},
            status_code=500,
        )

    # A route, not a StaticFiles mount: evidence is generated at runtime, so it must
    # never be treated as build-time static content (e.g. promoted to a CDN).
    # Files are a cache: missing evidence is regenerated from the source imagery and
    # served only if it matches the SHA-256 recorded when the run was made.
    @app.get("/artifacts/{run_id}/{name}", include_in_schema=False)
    def artifact(run_id: str, name: str) -> Response:
        if "/" in name or "\\" in name or ".." in name or not name.endswith(".png"):
            raise HTTPException(404)
        try:
            data = evidence_bytes(run_id, name)
        except evidence.EvidenceUnavailable as e:
            raise HTTPException(404) from e
        except evidence.EvidenceMismatch as e:
            log.error("evidence integrity failure: %s", e)
            raise HTTPException(500, "evidence failed its integrity check") from e
        return Response(
            data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    _register(app)
    if s.frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=s.frontend_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            target = s.frontend_dist / path
            if path and target.is_file():
                return FileResponse(target)
            return FileResponse(s.frontend_dist / "index.html")

    return app


# --------------------------------------------------------------------------- deps


def session() -> Any:
    with Session(STATE.engine) as ses:
        yield ses


SessionDep = Annotated[Session, Depends(session)]


class Actor(BaseModel):
    user: str
    role: Role


def actor(
    x_demo_user: Annotated[str | None, Header()] = None,
    x_demo_role: Annotated[str | None, Header()] = None,
) -> Actor:
    """Demo identity from headers. NOT authentication: the UI role switcher sets these."""
    role = x_demo_role if x_demo_role in ("analyst", "reviewer", "supervisor") else "analyst"
    return Actor(user=(x_demo_user or "demo.analyst")[:60], role=role)  # type: ignore[arg-type]


ActorDep = Annotated[Actor, Depends(actor)]


def evidence_bytes(run_id: str, name: str) -> bytes:
    with Session(STATE.engine) as ses:
        run = ses.get(RunRow, run_id)
        if run is None:
            raise evidence.EvidenceUnavailable(run_id)
        fid = name.split("_", 1)[0] if "_" in name else None
        frow = ses.get(FindingRow, fid) if fid else None
        aoi = ses.get(AoiRow, run.aoi_id)
        assert aoi is not None
        run_d = run.model_dump(mode="json")
        grid = GridSpec.from_dict(aoi.grid)
        finding_d = None if frow is None else frow.payload
    return evidence.get_evidence(
        STATE.pack, STATE.settings.artifact_dir, run_d, grid, name, finding_d
    )


def _finding(ses: Session, finding_id: str) -> Finding:
    row = ses.get(FindingRow, finding_id)
    if row is None:
        raise HTTPException(404, "finding not found")
    return Finding.model_validate(row.payload)


def _case(ses: Session, case_id: str) -> CaseRow:
    row = ses.get(CaseRow, case_id)
    if row is None:
        raise HTTPException(404, "case not found")
    return row


def _feature(case: CaseRow, f: Finding) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": case.id,
        "geometry": f.geometry,
        "properties": {
            "case_id": case.id,
            "finding_id": f.id,
            "aoi_id": case.aoi_id,
            "status": case.status,
            "priority_band": case.priority_band,
            "priority_score": case.priority_score,
            "transition": case.transition,
            "transition_label": f.transition_label,
            "area_ha": case.area_ha,
            "confidence": case.confidence,
            "district": case.district,
            "observed_t1": f"{case.observed_t1:%Y-%m-%d}",
            "observed_t2": f"{case.observed_t2:%Y-%m-%d}",
            "centroid": list(f.centroid),
        },
    }


# --------------------------------------------------------------------------- request bodies


class PolygonIn(BaseModel):
    name: str
    kind: str = "government_land"
    geometry: dict[str, Any]
    source: str = "User import"
    official: bool = False
    buffer_m: float = 200.0


class RunIn(BaseModel):
    aoi_id: str
    t1_scene_id: str
    t2_scene_id: str


class ActionIn(BaseModel):
    action: workflow.Action
    note: str | None = None
    reject_reason: str | None = None
    assignee: str | None = None


class AskIn(BaseModel):
    question: str


class CycleIn(BaseModel):
    strategy: StrategyName = "marginal_value"


# --------------------------------------------------------------------------- routes


def _register(app: FastAPI) -> None:
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        m = STATE.pack.manifest
        return {
            "data_mode": "demo_pack",
            "pack_built_at": m.get("built_at"),
            "pack_note": m.get("note"),
            "sources": m.get("sources", {}),
            "ai": {
                "enabled": STATE.llm is not None,
                "provider": "gemini" if STATE.llm else None,
                "model": STATE.llm.model if STATE.llm else None,
                "fallback": "deterministic templates",
            },
            "algorithm": "rule-v1.0 (heuristic, indicative)",
            "identity": "demo role switcher (not authentication)",
        }

    @app.get("/api/districts")
    def districts() -> dict[str, Any]:
        return STATE.pack.districts_geojson()

    @app.get("/api/aois")
    def list_aois(ses: SessionDep) -> list[dict[str, Any]]:
        out = []
        for a in ses.exec(select(AoiRow)).all():
            cases = ses.exec(select(CaseRow).where(CaseRow.aoi_id == a.id)).all()
            out.append(
                {
                    **a.model_dump(mode="json"),
                    "scene_count": len(STATE.pack.scenes(a.id))
                    if a.id in STATE.pack.aoi_ids
                    else 0,
                    "case_count": len(cases),
                    "open_cases": sum(c.status in ("UNVERIFIED", "UNDER_REVIEW") for c in cases),
                    "p1_open": sum(
                        c.priority_band == "P1" and c.status in ("UNVERIFIED", "UNDER_REVIEW")
                        for c in cases
                    ),
                    "changed_area_ha": round(sum(c.area_ha for c in cases), 2),
                }
            )
        return out

    @app.get("/api/aois/{aoi_id}")
    def get_aoi(aoi_id: str, ses: SessionDep) -> dict[str, Any]:
        a = ses.get(AoiRow, aoi_id)
        if a is None:
            raise HTTPException(404, "area not found")
        polys = ses.exec(select(PolygonRow).where(PolygonRow.aoi_id == aoi_id)).all()
        pack_fc = (
            STATE.pack.polygons_geojson(aoi_id)
            if aoi_id in STATE.pack.aoi_ids
            else {"features": []}
        )
        buffers = [f for f in pack_fc["features"] if f["properties"]["kind"] == "watch_buffer"]
        scenes = STATE.pack.scenes(aoi_id) if aoi_id in STATE.pack.aoi_ids else []
        catalog = STATE.pack.catalog(aoi_id) if aoi_id in STATE.pack.aoi_ids else []
        return {
            **a.model_dump(mode="json"),
            "polygons": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": p.geometry,
                        "properties": {
                            "id": p.id,
                            "name": p.name,
                            "kind": p.kind,
                            "source": p.source,
                            "official": p.official,
                            "created_by": p.created_by,
                        },
                    }
                    for p in polys
                ]
                + buffers,
            },
            "scenes": [sc.model_dump(mode="json") for sc in scenes],
            "catalog_stats": {
                "acquisitions": sum(1 for r in catalog if r.get("contains_aoi")),
                "clear_le_20pct": sum(
                    1
                    for r in catalog
                    if r.get("contains_aoi") and (r.get("cloud_cover") or 100) <= 20
                ),
                "first": catalog[0]["datetime"] if catalog else None,
                "last": catalog[-1]["datetime"] if catalog else None,
            },
            "runs": [
                r.model_dump(mode="json")
                for r in ses.exec(
                    select(RunRow).where(RunRow.aoi_id == aoi_id).order_by(RunRow.created_at.desc())  # type: ignore[attr-defined]
                ).all()
            ],
        }

    @app.get("/api/aois/{aoi_id}/catalog")
    def aoi_catalog(aoi_id: str) -> list[dict[str, Any]]:
        if aoi_id not in STATE.pack.aoi_ids:
            raise HTTPException(404, "area not in data pack")
        return [r for r in STATE.pack.catalog(aoi_id) if r.get("contains_aoi")]

    @app.get("/api/aois/{aoi_id}/scenes/{scene_id}/truecolor.png")
    def scene_truecolor(aoi_id: str, scene_id: str) -> FileResponse:
        """True-colour rendering of a captured scene (cached on disk)."""
        if aoi_id not in STATE.pack.aoi_ids or scene_id not in {
            sc.scene_id for sc in STATE.pack.scenes(aoi_id)
        }:
            raise HTTPException(404, "scene not in data pack")
        path = STATE.settings.var_dir / "scenes" / aoi_id / f"{scene_id}.png"
        if not path.exists():
            with _render_lock(str(path)):
                if not path.exists():  # another request may have rendered it meanwhile
                    obs = STATE.pack.load_observation(aoi_id, scene_id)
                    render.write_png(render.true_color(obs.bands, obs.valid), path)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/aois/{aoi_id}/corners")
    def aoi_corners(aoi_id: str, ses: SessionDep) -> list[list[float]]:
        """Image corners (TL, TR, BR, BL) in lon/lat for raster overlays."""
        a = ses.get(AoiRow, aoi_id)
        if a is None:
            raise HTTPException(404, "area not found")
        return grid_corners(GridSpec.from_dict(a.grid))

    @app.post("/api/aois/{aoi_id}/polygons")
    def import_polygon(aoi_id: str, body: PolygonIn, who: ActorDep) -> dict[str, Any]:
        geom = body.geometry
        if geom.get("type") == "FeatureCollection":
            geom = geom["features"][0]["geometry"]
        elif geom.get("type") == "Feature":
            geom = geom["geometry"]
        try:
            row = add_polygon(
                STATE.engine,
                aoi_id,
                body.name,
                body.kind,
                geom,
                body.source,
                body.official,
                who.user,
                body.buffer_m,
            )
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e)) from e
        return row.model_dump(mode="json")

    @app.post("/api/runs")
    def create_run(body: RunIn, who: ActorDep) -> dict[str, Any]:
        try:
            summary = run_detection_for_aoi(
                STATE.engine,
                STATE.pack,
                body.aoi_id,
                body.t1_scene_id,
                body.t2_scene_id,
                STATE.settings.artifact_dir,
                triggered_by="user",
                actor=f"{who.user} (detector run)",
            )
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        return {
            "run": summary.run.model_dump(mode="json"),
            "finding_count": len(summary.findings),
            "case_ids": summary.case_ids,
        }

    @app.get("/api/runs")
    def list_runs(ses: SessionDep, aoi_id: str | None = None) -> list[dict[str, Any]]:
        q = select(RunRow).order_by(RunRow.created_at.desc())  # type: ignore[attr-defined]
        if aoi_id:
            q = q.where(RunRow.aoi_id == aoi_id)
        return [r.model_dump(mode="json") for r in ses.exec(q).all()]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, ses: SessionDep) -> dict[str, Any]:
        r = ses.get(RunRow, run_id)
        if r is None:
            raise HTTPException(404, "run not found")
        findings = ses.exec(select(FindingRow).where(FindingRow.run_id == run_id)).all()
        return {
            **r.model_dump(mode="json"),
            "findings": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": f.id,
                        "geometry": f.payload["geometry"],
                        "properties": {
                            "finding_id": f.id,
                            # Recorded-only findings carry their own id as case_id.
                            "case_id": f.case_id or f.id,
                            "linked_case_id": f.case_id,
                            "triage": f.triage,
                            "transition": f.transition,
                            "transition_label": f.payload.get("transition_label"),
                            "area_ha": f.area_ha,
                            "confidence": f.confidence,
                            "priority_band": f.priority_band,
                            "priority_score": f.priority_score,
                            "status": "RECORDED" if f.case_id is None else "CASE",
                            "district": f.district,
                            "observed_t1": f.payload["t1"]["datetime"][:10],
                            "observed_t2": f.payload["t2"]["datetime"][:10],
                            "centroid": f.payload["centroid"],
                        },
                    }
                    for f in findings
                ],
            },
        }

    @app.get("/api/findings/{finding_id}")
    def get_finding(finding_id: str, ses: SessionDep) -> dict[str, Any]:
        return _finding(ses, finding_id).model_dump(mode="json")

    @app.get("/api/cases")
    def list_cases(
        ses: SessionDep,
        status: str | None = None,
        band: str | None = None,
        aoi_id: str | None = None,
        district: str | None = None,
        transition: str | None = None,
    ) -> dict[str, Any]:
        q = select(CaseRow)
        for col, val in (
            (CaseRow.status, status),
            (CaseRow.priority_band, band),
            (CaseRow.aoi_id, aoi_id),
            (CaseRow.district, district),
            (CaseRow.transition, transition),
        ):
            if val:
                q = q.where(col == val)
        rows = sorted(ses.exec(q).all(), key=lambda c: -c.priority_score)
        feats = []
        for c in rows:
            feats.append(_feature(c, _finding(ses, c.finding_id)))
        return {"type": "FeatureCollection", "features": feats}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, ses: SessionDep, who: ActorDep) -> dict[str, Any]:
        c = _case(ses, case_id)
        f = _finding(ses, c.finding_id)
        events = ses.exec(
            select(CaseEventRow).where(CaseEventRow.case_id == case_id).order_by(CaseEventRow.seq)  # type: ignore[arg-type]
        ).all()
        chain = verify_chain(event_dicts(list(events)))
        run = ses.get(RunRow, c.run_id)
        return {
            "case": c.model_dump(mode="json"),
            "finding": f.model_dump(mode="json"),
            "run": None if run is None else run.model_dump(mode="json"),
            "events": [e.model_dump(mode="json") for e in events],
            "audit_chain": {"ok": chain.ok, "checked": chain.checked, "reason": chain.reason},
            "allowed_actions": workflow.allowed_actions(c.status, who.role),  # type: ignore[arg-type]
            "reject_reasons": list(workflow.REJECT_REASONS),
        }

    @app.post("/api/cases/{case_id}/actions")
    def case_action(case_id: str, body: ActionIn, who: ActorDep) -> dict[str, Any]:
        try:
            c = apply_case_action(
                STATE.engine,
                case_id,
                body.action,
                who.user,
                who.role,
                body.note,
                body.reject_reason,
                body.assignee,
            )
        except KeyError as e:
            raise HTTPException(404, "case not found") from e
        except workflow.WorkflowError as e:
            raise HTTPException(409, str(e)) from e
        return c.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/attachments")
    async def attach(
        case_id: str,
        who: ActorDep,
        file: Annotated[UploadFile, File()],
        note: Annotated[str, Form()] = "",
        kind: Annotated[str, Form()] = "attachment",
    ) -> dict[str, Any]:
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file too large (4 MB max)")
        sha = hashlib.sha256(data).hexdigest()
        safe = "".join(ch for ch in (file.filename or "upload") if ch.isalnum() or ch in "._-")[:80]
        stored = f"{sha[:12]}_{safe}"
        with Session(STATE.engine) as ses:
            _case(ses, case_id)
            # Stored in the database so field evidence survives serverless instances.
            ses.merge(
                UploadBlobRow(
                    key=f"{case_id}/{stored}",
                    case_id=case_id,
                    content_type=file.content_type or "application/octet-stream",
                    sha256=sha,
                    data=data,
                )
            )
            ses.commit()
        try:
            c = apply_case_action(
                STATE.engine,
                case_id,
                "attach",
                who.user,
                who.role,
                note or None,
                extra={
                    "file": safe,
                    "sha256": sha,
                    "bytes": len(data),
                    "kind": "field_note" if kind == "field_note" else "attachment",
                    "uri": f"/api/uploads/{case_id}/{stored}",
                },
            )
        except workflow.WorkflowError as e:
            raise HTTPException(409, str(e)) from e
        return c.model_dump(mode="json")

    @app.get("/api/uploads/{case_id}/{name}")
    def get_upload(case_id: str, name: str, ses: SessionDep) -> Response:
        row = ses.get(UploadBlobRow, f"{case_id}/{name}")
        if row is None:
            raise HTTPException(404)
        return Response(
            row.data,
            media_type=row.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/cases/{case_id}/interpret")
    def interpret_case(case_id: str, who: ActorDep) -> dict[str, Any]:
        with Session(STATE.engine) as ses:
            c = _case(ses, case_id)
            f = _finding(ses, c.finding_id)
            pr = PriorityResult.model_validate(c.priority)

        def cache_get(key: str) -> dict[str, Any] | None:
            with Session(STATE.engine) as ses:
                row = ses.get(AiCacheRow, key)
                return None if row is None else row.payload

        def cache_set(key: str, payload: dict[str, Any]) -> None:
            with Session(STATE.engine) as ses:
                ses.merge(AiCacheRow(key=key, kind="interpretation", payload=payload))
                ses.commit()

        images: list[tuple[bytes, str]] = []
        for e in f.evidence:
            if (
                e.kind in ("image_before", "image_after")
                and e.uri
                and e.uri.startswith("/artifacts/")
            ):
                run_id, _, name = e.uri.removeprefix("/artifacts/").partition("/")
                try:
                    images.append((evidence_bytes(run_id, name), "image/png"))
                except (evidence.EvidenceUnavailable, evidence.EvidenceMismatch):
                    log.warning("evidence image %s unavailable for interpretation", e.uri)
        interp, meta_ = interpret(f, pr, STATE.llm, cache_get, cache_set, images or None)
        with Session(STATE.engine) as ses:
            c = _case(ses, case_id)
            c.interpretation = {
                **interp.model_dump(),
                "meta": meta_,
                "generated_at": datetime.now(UTC).isoformat(),
            }
            ses.add(c)
            ses.commit()
        return {"interpretation": interp.model_dump(), "meta": meta_}

    @app.get("/api/cases/{case_id}/report", response_class=HTMLResponse)
    def case_report(case_id: str, ses: SessionDep) -> HTMLResponse:
        c = _case(ses, case_id)
        f = _finding(ses, c.finding_id)
        events = ses.exec(
            select(CaseEventRow).where(CaseEventRow.case_id == case_id).order_by(CaseEventRow.seq)  # type: ignore[arg-type]
        ).all()
        aoi = ses.get(AoiRow, c.aoi_id)
        chain = verify_chain(event_dicts(list(events)))
        return HTMLResponse(reports.case_report_html(c, f, list(events), aoi, chain.ok))

    @app.get("/api/export/cases.geojson")
    def export_geojson(ses: SessionDep) -> JSONResponse:
        feats = [_feature(c, _finding(ses, c.finding_id)) for c in ses.exec(select(CaseRow)).all()]
        return JSONResponse(
            {"type": "FeatureCollection", "features": feats},
            headers={"Content-Disposition": "attachment; filename=geointx_cases.geojson"},
        )

    @app.get("/api/export/cases.csv")
    def export_csv(ses: SessionDep) -> Response:
        rows = [(c, _finding(ses, c.finding_id)) for c in ses.exec(select(CaseRow)).all()]
        return Response(
            reports.cases_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=geointx_cases.csv"},
        )

    @app.get("/api/analytics")
    def analytics(ses: SessionDep) -> dict[str, Any]:
        return reports.analytics(ses, STATE.pack)

    @app.get("/api/boundaries")
    def boundaries(ses: SessionDep) -> dict[str, Any]:
        """Monitored boundaries ranked by detected change inside / in the watch buffer."""
        return Tools(ses).wetland_ranking(NoArgs())

    @app.post("/api/assistant")
    def ask(body: AskIn, ses: SessionDep) -> dict[str, Any]:
        q = body.question.strip()[:500]
        if not q:
            raise HTTPException(400, "empty question")
        aois = {a.id: a.name for a in ses.exec(select(AoiRow)).all()}
        districts = sorted(
            {f["properties"]["name"] for f in STATE.pack.districts_geojson()["features"]}
        )
        return assistant.ask(q, Tools(ses), aois, districts, STATE.llm)

    @app.get("/api/scheduler/plan")
    def scheduler_plan(ses: SessionDep) -> dict[str, Any]:
        previews = agent_loop.plan(ses, STATE.pack)
        return {"now": datetime.now(UTC).isoformat(), "candidates": [p.as_dict() for p in previews]}

    @app.post("/api/scheduler/cycle")
    def scheduler_cycle(body: CycleIn) -> dict[str, Any]:
        row, summary, _ = agent_loop.run_cycle(
            STATE.engine, STATE.pack, STATE.settings.artifact_dir, body.strategy, STATE.llm
        )
        return {
            "decision": row.model_dump(mode="json"),
            "run": None if summary is None else summary.run.model_dump(mode="json"),
            "case_ids": [] if summary is None else summary.case_ids,
        }

    @app.get("/api/scheduler/decisions")
    def scheduler_decisions(ses: SessionDep) -> list[dict[str, Any]]:
        rows = ses.exec(select(SchedulerDecisionRow).order_by(SchedulerDecisionRow.ts.desc())).all()  # type: ignore[attr-defined]
        return [r.model_dump(mode="json") for r in rows]

    @app.get("/api/activity")
    def activity(ses: SessionDep, limit: int = 25) -> list[dict[str, Any]]:
        evs = ses.exec(
            select(CaseEventRow).order_by(CaseEventRow.id.desc()).limit(limit)  # type: ignore[union-attr]
        ).all()
        return [e.model_dump(mode="json") for e in evs]


def main() -> None:  # pragma: no cover
    import os

    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
