"""Which findings become verification cases (pure logic, no I/O).

Every finding is recorded (it counts toward land-use / land-cover statistics).
Only findings worth an official's time open a case:

* P3 (low priority) findings are recorded, not queued.
* In encroachment-monitoring areas, gains (more water, regrowth) are recorded
  but not queued: they do not remove natural cover.
* A finding that overlaps an existing case of the same change type does not
  open a duplicate; it is appended to that case as a re-observation. A finding
  of the opposite change type over an existing case is appended as a reversal
  (evidence the earlier change was transient).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shapely.geometry.base import BaseGeometry

LOSS_TRANSITIONS = {
    "water_loss",
    "wetland_vegetation_loss",
    "forest_clearing",
    "cropland_to_bare_or_built",
    "vegetation_to_bare_or_built",
}
VEG_LOSS = {
    "wetland_vegetation_loss",
    "forest_clearing",
    "cropland_to_bare_or_built",
    "vegetation_to_bare_or_built",
}
MIN_OVERLAP = 0.3  # share of the smaller region

Decision = Literal[
    "queued",
    "re_observed",
    "reversal_observed",
    "recorded_low_priority",
    "recorded_not_encroachment_relevant",
    "recorded_gain",
]


@dataclass(frozen=True)
class ExistingCase:
    case_id: str
    transition: str
    geometry: BaseGeometry  # WGS84


def opposite(a: str, b: str) -> bool:
    if {a, b} == {"water_loss", "water_gain"}:
        return True
    return (a in VEG_LOSS and b == "revegetation") or (b in VEG_LOSS and a == "revegetation")


def same_family(a: str, b: str) -> bool:
    return a == b or (a in VEG_LOSS and b in VEG_LOSS)


def overlap_share(a: BaseGeometry, b: BaseGeometry) -> float:
    smaller = min(a.area, b.area)
    if smaller <= 0 or not a.intersects(b):
        return 0.0
    return float(a.intersection(b).area / smaller)


def match_existing(
    geom: BaseGeometry, transition: str, existing: list[ExistingCase]
) -> tuple[Literal["same", "reversal"], ExistingCase] | None:
    best: tuple[float, Literal["same", "reversal"], ExistingCase] | None = None
    for ex in existing:
        share = overlap_share(geom, ex.geometry)
        if share < MIN_OVERLAP:
            continue
        kind: Literal["same", "reversal"] | None = (
            "same"
            if same_family(transition, ex.transition)
            else "reversal"
            if opposite(transition, ex.transition)
            else None
        )
        if kind and (best is None or share > best[0]):
            best = (share, kind, ex)
    return None if best is None else (best[1], best[2])


def decide(
    transition: str,
    band: str,
    mode: str,
    geom: BaseGeometry,
    existing: list[ExistingCase],
) -> tuple[Decision, ExistingCase | None]:
    m = match_existing(geom, transition, existing)
    if m is not None:
        kind, ex = m
        return ("re_observed" if kind == "same" else "reversal_observed"), ex
    if transition == "revegetation":
        return "recorded_gain", None
    if mode == "encroachment" and transition not in LOSS_TRANSITIONS:
        return "recorded_not_encroachment_relevant", None
    if band == "P3":
        return "recorded_low_priority", None
    return "queued", None
