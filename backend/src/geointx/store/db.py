"""SQLite persistence (SQLModel). Geometry is stored as GeoJSON text in WGS84."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, event
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine


def utcnow() -> datetime:
    return datetime.now(UTC)


class AoiRow(SQLModel, table=True):
    __tablename__ = "aoi"
    id: str = Field(primary_key=True)
    name: str
    mode: str  # lulc | encroachment
    description: str = ""
    bbox: list[float] = Field(sa_column=Column(JSON))
    grid: dict[str, Any] = Field(sa_column=Column(JSON))
    district: str | None = None
    source: str = "seed"
    monitoring_active: bool = True
    target_revisit_days: int = 30
    last_observed_at: datetime | None = None
    last_run_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class PolygonRow(SQLModel, table=True):
    __tablename__ = "monitored_polygon"
    id: str = Field(primary_key=True)
    aoi_id: str = Field(index=True, foreign_key="aoi.id")
    name: str
    kind: str
    geometry: dict[str, Any] = Field(sa_column=Column(JSON))
    source: str
    official: bool = False
    buffer_m: float = 200.0
    created_by: str = "system"
    created_at: datetime = Field(default_factory=utcnow)


class RunRow(SQLModel, table=True):
    __tablename__ = "change_run"
    id: str = Field(primary_key=True)
    aoi_id: str = Field(index=True, foreign_key="aoi.id")
    t1_scene_id: str
    t2_scene_id: str
    t1_datetime: datetime
    t2_datetime: datetime
    later_scene_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    data_mode: str = "demo_pack"  # demo_pack | live
    triggered_by: str = "user"  # user | scheduler
    algorithm_version: str
    stats: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    artifacts: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    overlay_corners: list[list[float]] = Field(default_factory=list, sa_column=Column(JSON))
    finding_count: int = 0
    case_count: int = 0
    reobserved_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class FindingRow(SQLModel, table=True):
    __tablename__ = "finding"
    id: str = Field(primary_key=True)
    run_id: str = Field(index=True, foreign_key="change_run.id")
    aoi_id: str = Field(index=True)
    transition: str
    area_ha: float
    confidence: float
    district: str | None = None
    priority_score: float | None = None
    priority_band: str | None = None
    triage: str | None = None  # see geointx.cases.triage.Decision
    case_id: str | None = None  # case opened for, or updated by, this finding
    payload: dict[str, Any] = Field(sa_column=Column(JSON))


class CaseRow(SQLModel, table=True):
    __tablename__ = "case_file"
    id: str = Field(primary_key=True)
    finding_id: str = Field(index=True, foreign_key="finding.id")
    run_id: str = Field(index=True)
    aoi_id: str = Field(index=True)
    status: str = "UNVERIFIED"
    priority_score: float
    priority_band: str
    priority: dict[str, Any] = Field(sa_column=Column(JSON))
    transition: str
    area_ha: float
    confidence: float
    district: str | None = None
    observed_t1: datetime
    observed_t2: datetime
    assignee: str | None = None
    reject_reason: str | None = None
    interpretation: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None


class CaseEventRow(SQLModel, table=True):
    __tablename__ = "case_event"
    id: int | None = Field(default=None, primary_key=True)
    case_id: str = Field(index=True, foreign_key="case_file.id")
    seq: int
    ts: str  # ISO timestamp, part of the hashed body
    actor: str
    role: str
    action: str
    from_status: str | None = None
    to_status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    prev_hash: str
    hash: str


class SchedulerDecisionRow(SQLModel, table=True):
    __tablename__ = "scheduler_decision"
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow)
    strategy: str
    decision_source: str  # deterministic | llm_validated | llm_rejected_fallback
    chosen_aoi_id: str | None
    chosen_scene_id: str | None
    reason: str
    candidates: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    executed_run_id: str | None = None


class AiCacheRow(SQLModel, table=True):
    __tablename__ = "ai_cache"
    key: str = Field(primary_key=True)
    kind: str
    payload: dict[str, Any] = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn: Any, _: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    SQLModel.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s
