"""Deterministic query tools the assistant is allowed to call.

The assistant (LLM or rule-based) can only select one of these tools and supply
validated arguments. All figures in an answer come from these results.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from geointx.store.db import AoiRow, CaseRow, FindingRow, PolygonRow, RunRow


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class ListCasesArgs(BaseModel):
    aoi_id: str | None = None
    district: str | None = None
    status: Literal["UNVERIFIED", "UNDER_REVIEW", "CONFIRMED", "REJECTED"] | None = None
    band: Literal["P1", "P2", "P3"] | None = None
    transition: str | None = None
    since_months: int | None = Field(None, ge=1, le=120)
    sort_by: Literal["priority", "area"] = "priority"
    limit: int = Field(10, ge=1, le=50)


class CaseArgs(BaseModel):
    case_id: str


class AggregateArgs(BaseModel):
    group_by: Literal["district", "transition", "aoi", "status", "year"]
    since_months: int | None = Field(None, ge=1, le=120)


class AreaArgs(BaseModel):
    aoi_id: str


class NoArgs(BaseModel):
    pass


def _case_brief(c: CaseRow) -> dict[str, Any]:
    return {
        "case_id": c.id,
        "aoi_id": c.aoi_id,
        "status": c.status,
        "priority_band": c.priority_band,
        "priority_score": c.priority_score,
        "transition": c.transition,
        "area_ha": c.area_ha,
        "confidence": c.confidence,
        "district": c.district,
        "observed_between": [f"{c.observed_t1:%Y-%m-%d}", f"{c.observed_t2:%Y-%m-%d}"],
    }


class Tools:
    def __init__(self, session: Session, now: datetime | None = None) -> None:
        self.s = session
        self.now = now or datetime.now(UTC)

    def _latest_observation(self) -> str | None:
        runs = self.s.exec(select(RunRow)).all()
        if not runs:
            return None
        return f"{max(_aware(r.t2_datetime) for r in runs):%Y-%m-%d}"

    def list_cases(self, a: ListCasesArgs) -> dict[str, Any]:
        q = select(CaseRow)
        if a.aoi_id:
            q = q.where(CaseRow.aoi_id == a.aoi_id)
        if a.district:
            q = q.where(CaseRow.district == a.district)
        if a.status:
            q = q.where(CaseRow.status == a.status)
        if a.band:
            q = q.where(CaseRow.priority_band == a.band)
        if a.transition:
            q = q.where(CaseRow.transition == a.transition)
        rows = list(self.s.exec(q).all())
        window = None
        if a.since_months:
            cutoff = self.now - timedelta(days=30.44 * a.since_months)
            rows = [r for r in rows if _aware(r.observed_t2) >= cutoff]
            window = f"observed on or after {cutoff:%Y-%m-%d}"
        key = (lambda r: r.priority_score) if a.sort_by == "priority" else (lambda r: r.area_ha)
        rows.sort(key=key, reverse=True)
        return {
            "filters": a.model_dump(exclude_none=True),
            "time_window": window,
            "latest_observation_in_system": self._latest_observation(),
            "total_matching": len(rows),
            "total_area_ha": round(sum(r.area_ha for r in rows), 2),
            "cases": [_case_brief(r) for r in rows[: a.limit]],
        }

    def get_case(self, a: CaseArgs) -> dict[str, Any]:
        c = self.s.get(CaseRow, a.case_id.upper())
        if c is None:
            return {"error": f"No case {a.case_id}"}
        f = self.s.get(FindingRow, c.finding_id)
        fp = f.payload if f else {}
        return {
            **_case_brief(c),
            "assignee": c.assignee,
            "priority_breakdown": c.priority.get("factors", []),
            "confidence_factors": fp.get("confidence_factors", []),
            "overlaps": fp.get("overlaps", []),
            "index_deltas": fp.get("index_deltas", {}),
            "baseline_landcover": fp.get("baseline_landcover", {}),
            "persistence": fp.get("persistence"),
            "scenes": {
                "before": fp.get("t1", {}).get("scene_id"),
                "after": fp.get("t2", {}).get("scene_id"),
            },
            "evidence": [
                {"id": e["id"], "kind": e["kind"], "description": e["description"]}
                for e in fp.get("evidence", [])
            ],
            "caveats": fp.get("caveats", []),
        }

    def aggregate(self, a: AggregateArgs) -> dict[str, Any]:
        rows = list(self.s.exec(select(CaseRow)).all())
        if a.since_months:
            cutoff = self.now - timedelta(days=30.44 * a.since_months)
            rows = [r for r in rows if _aware(r.observed_t2) >= cutoff]
        groups: dict[str, dict[str, float]] = defaultdict(lambda: {"cases": 0, "area_ha": 0.0})
        for r in rows:
            k = {
                "district": r.district or "Unknown",
                "transition": r.transition,
                "aoi": r.aoi_id,
                "status": r.status,
                "year": f"{r.observed_t2:%Y}",
            }[a.group_by]
            groups[k]["cases"] += 1
            groups[k]["area_ha"] = round(groups[k]["area_ha"] + r.area_ha, 3)
        return {
            "group_by": a.group_by,
            "latest_observation_in_system": self._latest_observation(),
            "groups": dict(sorted(groups.items(), key=lambda kv: -kv[1]["area_ha"])),
        }

    def wetland_ranking(self, _: NoArgs) -> dict[str, Any]:
        polys = self.s.exec(
            select(PolygonRow).where(
                PolygonRow.kind.in_(  # type: ignore[attr-defined]
                    ("wetland", "protected_area", "water_body", "government_land")
                )
            )
        ).all()
        out: list[dict[str, Any]] = []
        for p in polys:
            inside = near = 0.0
            ids: list[str] = []
            open_ids: list[str] = []
            for f in self.s.exec(select(FindingRow).where(FindingRow.aoi_id == p.aoi_id)).all():
                case = self.s.exec(select(CaseRow).where(CaseRow.finding_id == f.id)).first()
                if case is None:  # e.g. revegetation: recorded, not a case
                    continue
                for o in f.payload.get("overlaps", []):
                    if o["polygon_id"] != p.id:
                        continue
                    inside += o["overlap_ha"]
                    if o["within_buffer"]:
                        near += f.area_ha
                    ids.append(case.id)
                    if case.status in ("UNVERIFIED", "UNDER_REVIEW"):
                        open_ids.append(case.id)
            out.append(
                {
                    "polygon_id": p.id,
                    "polygon": p.name,
                    "kind": p.kind,
                    "aoi_id": p.aoi_id,
                    "boundary_source": p.source,
                    "official_boundary": p.official,
                    "changed_area_inside_ha": round(inside, 2),
                    "changed_area_in_buffer_ha": round(near, 2),
                    "case_ids": sorted(set(ids)),
                    "open_case_ids": sorted(set(open_ids)),
                }
            )
        out.sort(key=lambda r: -(r["changed_area_inside_ha"] + r["changed_area_in_buffer_ha"]))
        return {
            "monitored_boundaries": out,
            "note": "Areas are summed over all analyses of each area (suspected change, cases only).",
        }

    def area_summary(self, a: AreaArgs) -> dict[str, Any]:
        aoi = self.s.get(AoiRow, a.aoi_id)
        if aoi is None:
            return {"error": f"No monitored area {a.aoi_id}"}
        runs = self.s.exec(select(RunRow).where(RunRow.aoi_id == aoi.id)).all()
        cases = self.s.exec(select(CaseRow).where(CaseRow.aoi_id == aoi.id)).all()
        by_t: dict[str, float] = defaultdict(float)
        for c in cases:
            by_t[c.transition] += c.area_ha
        by_s: dict[str, int] = defaultdict(int)
        for c in cases:
            by_s[c.status] += 1
        return {
            "aoi_id": aoi.id,
            "name": aoi.name,
            "mode": aoi.mode,
            "district": aoi.district,
            "analyses_run": len(runs),
            "observation_periods": [
                f"{r.t1_datetime:%Y-%m-%d} to {r.t2_datetime:%Y-%m-%d}" for r in runs
            ],
            "cases": len(cases),
            "cases_by_status": dict(by_s),
            "changed_area_by_transition_ha": {k: round(v, 2) for k, v in by_t.items()},
            "top_cases": [
                _case_brief(c) for c in sorted(cases, key=lambda c: -c.priority_score)[:5]
            ],
        }


TOOL_SPECS: dict[str, tuple[type[BaseModel], str]] = {
    "list_cases": (ListCasesArgs, "Filter and rank detected-change cases."),
    "get_case": (CaseArgs, "Full evidence, priority breakdown and status of one case."),
    "aggregate": (AggregateArgs, "Case counts and changed area grouped by a dimension."),
    "wetland_ranking": (NoArgs, "Monitored wetlands/protected areas ranked by detected change."),
    "area_summary": (AreaArgs, "Summary of detected change in one monitored area."),
}


def call_tool(tools: Tools, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_SPECS:
        raise ValueError(f"unknown tool {name}")
    model, _ = TOOL_SPECS[name]
    parsed = model.model_validate(args)
    result: dict[str, Any] = getattr(tools, name)(parsed)
    return result
