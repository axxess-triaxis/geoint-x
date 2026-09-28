"""Application services: glue between pack/imagery, pipeline, store and workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import box, shape
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from geointx.cases import triage, workflow
from geointx.cases.audit import GENESIS, event_hash
from geointx.geo.grid import GridSpec
from geointx.geo.overlap import MonitoredPolygon
from geointx.imagery.pack import DemoPack
from geointx.models import CaseStatus, Finding, Role
from geointx.pipeline import AoiContext, run_detection
from geointx.priority.engine import prioritise
from geointx.store.db import (
    AoiRow,
    CaseEventRow,
    CaseRow,
    FindingRow,
    PolygonRow,
    RunRow,
    utcnow,
)

# --------------------------------------------------------------------------- seeding


def district_of(pack: DemoPack, lon: float, lat: float) -> str | None:
    from shapely.geometry import Point

    pt = Point(lon, lat)
    for f in pack.districts_geojson()["features"]:
        if shape(f["geometry"]).contains(pt):
            return str(f["properties"]["name"])
    return None


def seed_from_pack(engine: Engine, pack: DemoPack) -> None:
    with Session(engine) as s:
        for aoi_id in pack.aoi_ids:
            meta = pack.aoi(aoi_id)
            if s.get(AoiRow, aoi_id) is None:
                b = meta["bbox"]
                s.add(
                    AoiRow(
                        id=aoi_id,
                        name=meta["name"],
                        mode=meta["mode"],
                        description=meta.get("description", ""),
                        bbox=meta["bbox"],
                        grid=meta["grid"],
                        district=district_of(pack, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2),
                        source="seed",
                    )
                )
            fc = pack.polygons_geojson(aoi_id)
            for f in fc["features"]:
                p = f["properties"]
                if p["kind"] == "watch_buffer" or s.get(PolygonRow, p["id"]) is not None:
                    continue
                s.add(
                    PolygonRow(
                        id=p["id"],
                        aoi_id=aoi_id,
                        name=p["name"],
                        kind=p["kind"],
                        geometry=f["geometry"],
                        source=p["source"],
                        official=bool(p.get("official", False)),
                        buffer_m=float(p.get("buffer_m", 200.0)),
                    )
                )
        try:
            s.commit()
        except IntegrityError:
            # Another instance seeded concurrently (shared Postgres): its rows win.
            s.rollback()


# --------------------------------------------------------------------------- polygons


def add_polygon(
    engine: Engine,
    aoi_id: str,
    name: str,
    kind: str,
    geometry: dict[str, Any],
    source: str,
    official: bool,
    created_by: str,
    buffer_m: float = 200.0,
) -> PolygonRow:
    geom = shape(geometry)
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("boundary must be a Polygon or MultiPolygon")
    if not geom.is_valid:
        geom = geom.buffer(0)
    with Session(engine) as s:
        aoi = s.get(AoiRow, aoi_id)
        if aoi is None:
            raise KeyError(aoi_id)
        if not geom.intersects(box(*aoi.bbox)):
            raise ValueError("boundary does not intersect the monitored area")
        n = s.exec(select(func.count()).select_from(PolygonRow)).one()
        row = PolygonRow(
            id=f"user-{n + 1:04d}",
            aoi_id=aoi_id,
            name=name,
            kind=kind,
            geometry=geom.__geo_interface__,
            source=source,
            official=official,
            buffer_m=buffer_m,
            created_by=created_by,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def polygons_for(s: Session, aoi_id: str) -> list[MonitoredPolygon]:
    rows = s.exec(select(PolygonRow).where(PolygonRow.aoi_id == aoi_id)).all()
    return [
        MonitoredPolygon(
            id=r.id,
            name=r.name,
            kind=r.kind,
            geometry_wgs84=shape(r.geometry),
            source=r.source,
            official=r.official,
            buffer_m=r.buffer_m,
        )
        for r in rows
    ]


# --------------------------------------------------------------------------- memory


def area_prior(s: Session, aoi_id: str) -> tuple[float, float, float | None]:
    """Beta(1,1) posterior of confirmation rate from reviewed cases in the AOI."""
    confirmed = s.exec(
        select(func.count())
        .select_from(CaseRow)
        .where(CaseRow.aoi_id == aoi_id, CaseRow.status == "CONFIRMED")
    ).one()
    rejected = s.exec(
        select(func.count())
        .select_from(CaseRow)
        .where(CaseRow.aoi_id == aoi_id, CaseRow.status == "REJECTED")
    ).one()
    a, b = 1 + confirmed, 1 + rejected
    rate = None if confirmed + rejected == 0 else a / (a + b)
    return float(a), float(b), rate


# --------------------------------------------------------------------------- detection


@dataclass
class RunSummary:
    run: RunRow
    findings: list[Finding]
    case_ids: list[str]


def grid_corners(grid: GridSpec) -> list[list[float]]:
    """Lon/lat of the grid's TL, TR, BR, BL corners (for map image overlays)."""
    from pyproj import Transformer

    t = Transformer.from_crs(grid.epsg, 4326, always_xy=True)
    x0, y0, x1, y1 = grid.bounds
    return [
        [round(v, 7) for v in t.transform(x, y)]
        for x, y in ((x0, y1), (x1, y1), (x1, y0), (x0, y0))
    ]


def _next_id(s: Session, model: Any, prefix: str) -> str:
    n = s.exec(select(func.count()).select_from(model)).one()
    return f"{prefix}-{n + 1:04d}"


def append_event(
    s: Session,
    case: CaseRow,
    actor: str,
    role: str,
    action: str,
    from_status: str | None,
    to_status: str | None,
    payload: dict[str, Any],
) -> CaseEventRow:
    last = s.exec(
        select(CaseEventRow)
        .where(CaseEventRow.case_id == case.id)
        .order_by(CaseEventRow.seq.desc())  # type: ignore[attr-defined]
    ).first()
    seq = 1 if last is None else last.seq + 1
    prev = GENESIS if last is None else last.hash
    body: dict[str, Any] = {
        "seq": seq,
        "case_id": case.id,
        "ts": datetime.now(UTC).isoformat(),
        "actor": actor,
        "role": role,
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "payload": payload,
    }
    ev = CaseEventRow(**body, prev_hash=prev, hash=event_hash(prev, body))
    s.add(ev)
    return ev


def event_dicts(events: list[CaseEventRow]) -> list[dict[str, Any]]:
    return [e.model_dump() for e in events]


def run_detection_for_aoi(
    engine: Engine,
    pack: DemoPack,
    aoi_id: str,
    t1_scene_id: str,
    t2_scene_id: str,
    artifact_root: Path,
    triggered_by: str = "user",
    actor: str = "system:detector",
) -> RunSummary:
    scenes = {sc.scene_id: sc for sc in pack.scenes(aoi_id)}
    if t1_scene_id not in scenes or t2_scene_id not in scenes:
        raise KeyError("scene not available for this area")
    t1_ref, t2_ref = scenes[t1_scene_id], scenes[t2_scene_id]
    if t1_ref.datetime >= t2_ref.datetime:
        raise ValueError("the 'before' observation must be earlier than the 'after' observation")
    later_ids = [sid for sid, sc in scenes.items() if sc.datetime > t2_ref.datetime]

    t1 = pack.load_observation(aoi_id, t1_scene_id)
    t2 = pack.load_observation(aoi_id, t2_scene_id)
    later = [pack.load_observation(aoi_id, sid) for sid in later_ids]
    baseline = pack.load_baseline(aoi_id)
    districts = [
        (f["properties"]["name"], shape(f["geometry"]))
        for f in pack.districts_geojson()["features"]
    ]

    with Session(engine) as s:
        aoi = s.get(AoiRow, aoi_id)
        if aoi is None:
            raise KeyError(aoi_id)
        run_id = _next_id(s, RunRow, "RUN")
        ctx = AoiContext(aoi_id=aoi_id, polygons=polygons_for(s, aoi_id), districts=districts)
        out = run_detection(
            run_id=run_id,
            t1=t1,
            t2=t2,
            later=later,
            baseline=baseline,
            ctx=ctx,
            artifact_dir=artifact_root / run_id,
            artifact_url_prefix=f"/artifacts/{run_id}",
        )
        corners = grid_corners(GridSpec.from_dict(aoi.grid))
        run = RunRow(
            id=run_id,
            aoi_id=aoi_id,
            t1_scene_id=t1_scene_id,
            t2_scene_id=t2_scene_id,
            t1_datetime=t1_ref.datetime,
            t2_datetime=t2_ref.datetime,
            later_scene_ids=later_ids,
            triggered_by=triggered_by,
            algorithm_version=out.result.algorithm_version,
            stats=out.result.stats,
            artifacts=[a.model_dump() for a in out.run_artifacts],
            overlay_corners=corners,
            finding_count=len(out.findings),
        )
        s.add(run)
        s.flush()
        _, _, prior_rate = area_prior(s, aoi_id)
        case_ids: list[str] = []
        n_cases = s.exec(select(func.count()).select_from(CaseRow)).one()
        existing = [
            triage.ExistingCase(c.id, c.transition, shape(fr.payload["geometry"]))
            for c, fr in s.exec(
                select(CaseRow, FindingRow)
                .where(CaseRow.aoi_id == aoi_id)
                .where(CaseRow.finding_id == FindingRow.id)
            ).all()
        ]
        rows: dict[str, FindingRow] = {}
        for f in out.findings:
            rows[f.id] = FindingRow(
                id=f.id,
                run_id=run_id,
                aoi_id=aoi_id,
                transition=f.transition,
                area_ha=f.area_ha,
                confidence=f.confidence,
                district=f.district,
                payload=f.model_dump(mode="json"),
            )
            s.add(rows[f.id])
        s.flush()
        reobserved = 0
        for f in out.findings:
            pr = prioritise(f, prior_rate)
            decision, match = triage.decide(
                f.transition, pr.band, aoi.mode, shape(f.geometry), existing
            )
            rows[f.id].triage = decision
            rows[f.id].priority_score = pr.score
            rows[f.id].priority_band = pr.band
            if match is not None:
                prior_case = s.get(CaseRow, match.case_id)
                assert prior_case is not None
                rows[f.id].case_id = prior_case.id
                append_event(
                    s,
                    prior_case,
                    actor,
                    "system",
                    decision,
                    None,
                    None,
                    {
                        "finding_id": f.id,
                        "run_id": run_id,
                        "transition": f.transition,
                        "area_ha": f.area_ha,
                        "observed_t2": f"{f.t2.datetime:%Y-%m-%d}",
                        "status_at_time": prior_case.status,
                    },
                )
                prior_case.updated_at = utcnow()
                s.add(prior_case)
                reobserved += 1
                continue
            if decision != "queued":
                continue
            n_cases += 1
            case = CaseRow(
                id=f"CASE-{n_cases:04d}",
                finding_id=f.id,
                run_id=run_id,
                aoi_id=aoi_id,
                priority_score=pr.score,
                priority_band=pr.band,
                priority=pr.model_dump(),
                transition=f.transition,
                area_ha=f.area_ha,
                confidence=f.confidence,
                district=f.district,
                observed_t1=f.t1.datetime,
                observed_t2=f.t2.datetime,
            )
            s.add(case)
            s.flush()
            append_event(
                s,
                case,
                actor,
                "system",
                "created",
                None,
                "UNVERIFIED",
                {"finding_id": f.id, "priority_score": pr.score, "priority_band": pr.band},
            )
            rows[f.id].case_id = case.id
            case_ids.append(case.id)
        run.case_count = len(case_ids)
        run.reobserved_count = reobserved
        aoi.last_observed_at = t2_ref.datetime
        aoi.last_run_id = run_id
        s.add(aoi)
        s.commit()
        s.refresh(run)
        return RunSummary(run=run, findings=out.findings, case_ids=case_ids)


# --------------------------------------------------------------------------- cases


def apply_case_action(
    engine: Engine,
    case_id: str,
    action: workflow.Action,
    actor: str,
    role: Role,
    note: str | None = None,
    reject_reason: str | None = None,
    assignee: str | None = None,
    extra: dict[str, Any] | None = None,
) -> CaseRow:
    with Session(engine) as s:
        case = s.get(CaseRow, case_id)
        if case is None:
            raise KeyError(case_id)
        before: CaseStatus = case.status  # type: ignore[assignment]
        after = workflow.transition(before, action, role, note, reject_reason)
        if action == "assign":
            if not assignee:
                raise workflow.WorkflowError("assign requires an assignee")
            case.assignee = assignee
        if action == "reject":
            case.reject_reason = reject_reason
        if action in ("confirm", "reject"):
            case.decided_at = utcnow()
        if action == "reopen":
            case.decided_at = None
            case.reject_reason = None
        case.status = after
        case.updated_at = utcnow()
        payload: dict[str, Any] = {
            k: v
            for k, v in {"note": note, "reject_reason": reject_reason, "assignee": assignee}.items()
            if v
        }
        if extra:
            payload.update(extra)
        append_event(s, case, actor, role, action, before, after, payload)
        s.add(case)
        s.commit()
        s.refresh(case)
        return case
