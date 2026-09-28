"""Monitoring loop: build legal candidates from real available scenes, decide, execute.

Candidates only ever come from observations that actually exist in the data
source (the demo pack's captured scenes). If no monitored area has a new usable
observation, the agent records a "wait" decision instead of inventing one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, func, select

from geointx.agent.preview import (
    AreaMemory,
    Candidate,
    Preview,
    clear_sky_outlook,
    preview,
)
from geointx.agent.strategy import Decision, StrategyName, decide
from geointx.ai.client import LlmClient
from geointx.cases.triage import LOSS_TRANSITIONS
from geointx.geo.grid import GridSpec
from geointx.imagery.pack import DemoPack, parse_dt
from geointx.services import RunSummary, area_prior, run_detection_for_aoi
from geointx.store.db import AoiRow, FindingRow, RunRow, SchedulerDecisionRow


def build_candidates(s: Session, pack: DemoPack) -> list[Candidate]:
    out: list[Candidate] = []
    for aoi in s.exec(select(AoiRow).where(AoiRow.monitoring_active == True)).all():  # noqa: E712
        if aoi.id not in pack.aoi_ids:
            continue
        scenes = sorted(pack.scenes(aoi.id), key=lambda sc: sc.datetime)
        if len(scenes) < 2:
            continue
        grid = GridSpec.from_dict(aoi.grid)
        mp = grid.width * grid.height / 1e6
        if aoi.last_observed_at is None:
            prev, nxt = scenes[0], scenes[-1]
        else:
            cursor = aoi.last_observed_at.replace(tzinfo=aoi.last_observed_at.tzinfo or UTC)
            newer = [sc for sc in scenes if sc.datetime > cursor]
            if not newer:
                continue
            older = [sc for sc in scenes if sc.datetime <= cursor]
            prev, nxt = older[-1], newer[0]
        out.append(
            Candidate(
                aoi_id=aoi.id,
                aoi_name=aoi.name,
                mode=aoi.mode,
                district=aoi.district,
                prev_scene=prev,
                next_scene=nxt,
                cursor=None
                if aoi.last_observed_at is None
                else aoi.last_observed_at.replace(tzinfo=aoi.last_observed_at.tzinfo or UTC),
                megapixels=mp,
                target_revisit_days=aoi.target_revisit_days,
            )
        )
    return out


def memory_for(s: Session, aoi: AoiRow) -> AreaMemory:
    a, b, _ = area_prior(s, aoi.id)
    intensity = None
    if aoi.last_run_id:
        changed = s.exec(
            select(func.coalesce(func.sum(FindingRow.area_ha), 0.0)).where(
                FindingRow.run_id == aoi.last_run_id,
                FindingRow.transition.in_(LOSS_TRANSITIONS),  # type: ignore[attr-defined]
            )
        ).one()
        grid = GridSpec.from_dict(aoi.grid)
        km2 = grid.width * grid.height * grid.pixel_area_m2 / 1e6
        intensity = float(changed) / km2  # changed hectares per km2 of AOI
    return AreaMemory(a, b, intensity)


def district_counts(s: Session) -> dict[str, float]:
    counts: dict[str, float] = {}
    for aoi in s.exec(select(AoiRow)).all():
        if aoi.district:
            counts.setdefault(aoi.district, 0.0)
    for run in s.exec(select(RunRow)).all():
        run_aoi = s.get(AoiRow, run.aoi_id)
        if run_aoi and run_aoi.district:
            counts[run_aoi.district] = counts.get(run_aoi.district, 0.0) + 1
    return counts


def plan(s: Session, pack: DemoPack, now: datetime | None = None) -> list[Preview]:
    now = now or datetime.now(UTC)
    cands = build_candidates(s, pack)
    if not cands:
        return []
    counts = district_counts(s)
    mean_mp = sum(c.megapixels for c in cands) / len(cands)
    previews = []
    for c in cands:
        aoi = s.get(AoiRow, c.aoi_id)
        assert aoi is not None
        catalog = [
            {"datetime": parse_dt(r["datetime"]), "cloud_cover": r.get("cloud_cover")}
            for r in pack.catalog(c.aoi_id)
            if r.get("contains_aoi")
        ]
        outlook, n = clear_sky_outlook(catalog, now)
        p = preview(c, memory_for(s, aoi), now, outlook, counts, mean_mp)
        p.notes.append(
            f"Clear-sky outlook next 60 days: {outlook:.0%} of {n} past acquisitions in this "
            "calendar window had <= 20% cloud."
        )
        previews.append(p)
    previews.sort(key=lambda p: p.score, reverse=True)
    return previews


def run_cycle(
    engine: Engine,
    pack: DemoPack,
    artifact_root: Path,
    strategy: StrategyName = "marginal_value",
    llm: LlmClient | None = None,
    execute: bool = True,
) -> tuple[SchedulerDecisionRow, RunSummary | None, Decision]:
    with Session(engine) as s:
        previews = plan(s, pack)
    decision = decide(previews, strategy, llm)
    summary: RunSummary | None = None
    if decision.chosen is not None and execute:
        c = decision.chosen.candidate
        summary = run_detection_for_aoi(
            engine,
            pack,
            c.aoi_id,
            c.prev_scene.scene_id,
            c.next_scene.scene_id,
            artifact_root,
            triggered_by="scheduler",
            actor="system:monitoring-agent",
        )
    with Session(engine) as s:
        row = SchedulerDecisionRow(
            strategy=decision.strategy,
            decision_source=decision.decision_source,
            chosen_aoi_id=None if decision.chosen is None else decision.chosen.candidate.aoi_id,
            chosen_scene_id=None
            if decision.chosen is None
            else decision.chosen.candidate.next_scene.scene_id,
            reason=decision.reason,
            candidates=[p.as_dict() for p in previews],
            executed_run_id=None if summary is None else summary.run.id,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
    return row, summary, decision
