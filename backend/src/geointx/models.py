"""Shared domain schemas.

The key boundary in this system: deterministic code produces a ``Finding``; the
GenAI layer may only *interpret* a Finding. Every measurement, coordinate and
evidence reference lives in the Finding, never in LLM output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TransitionName = Literal[
    "water_loss",
    "water_gain",
    "forest_clearing",
    "cropland_to_bare_or_built",
    "vegetation_to_bare_or_built",
    "wetland_vegetation_loss",
    "revegetation",
]
CaseStatus = Literal["UNVERIFIED", "UNDER_REVIEW", "CONFIRMED", "REJECTED"]
Role = Literal["analyst", "reviewer", "supervisor"]
AoiMode = Literal["lulc", "encroachment"]
PriorityBand = Literal["P1", "P2", "P3"]


class SceneRef(BaseModel):
    """Provenance of one satellite observation."""

    scene_id: str
    collection: str
    datetime: datetime
    cloud_cover: float | None = Field(default=None, description="Scene-level cloud % from STAC")
    aoi_valid_fraction: float | None = Field(
        default=None, description="Fraction of AOI pixels clear (SCL) in this scene"
    )
    platform: str | None = None
    source_href: str | None = Field(default=None, description="STAC item URL")
    license: str = "Copernicus Sentinel data (free, full and open)"


class EvidenceItem(BaseModel):
    id: str
    kind: Literal[
        "image_before",
        "image_after",
        "change_mask",
        "boundary",
        "baseline_landcover",
        "temporal_history",
        "scene_metadata",
        "field_note",
        "attachment",
    ]
    description: str
    uri: str | None = None
    sha256: str | None = None


class ConfidenceFactor(BaseModel):
    name: str
    value: float
    weight: float
    explanation: str


class OverlapInfo(BaseModel):
    polygon_id: str
    polygon_name: str
    polygon_kind: str
    overlap_ha: float
    fraction_of_finding_inside: float
    crosses_boundary: bool
    within_buffer: bool
    distance_to_boundary_m: float


class Finding(BaseModel):
    """A structured, deterministic change detection result."""

    id: str
    run_id: str
    aoi_id: str
    transition: TransitionName
    transition_label: str
    geometry: dict[str, Any]  # GeoJSON Polygon/MultiPolygon, EPSG:4326
    centroid: tuple[float, float]  # lon, lat
    area_ha: float
    pixel_count: int
    t1: SceneRef
    t2: SceneRef
    index_means_t1: dict[str, float]
    index_means_t2: dict[str, float]
    index_deltas: dict[str, float]
    baseline_landcover: dict[str, float] = Field(
        default_factory=dict, description="Share of finding pixels by baseline class name"
    )
    persistence: float | None = Field(
        default=None, description="Share of pixels still in the changed state in later observations"
    )
    confidence: float
    confidence_factors: list[ConfidenceFactor]
    overlaps: list[OverlapInfo] = Field(default_factory=list)
    district: str | None = None
    algorithm_version: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class PriorityFactor(BaseModel):
    name: str
    value: float
    weight: float
    contribution: float
    explanation: str


class PriorityResult(BaseModel):
    score: float
    band: PriorityBand
    factors: list[PriorityFactor]
    engine_version: str


class Interpretation(BaseModel):
    """GenAI output. It may reference evidence only by ids present in the Finding."""

    summary: str
    evidence_refs: list[str]
    plausible_explanations: list[str]
    verification_steps: list[str]
    caveats: list[str]
    source: Literal["gemini", "template"] = "template"
    model: str | None = None
