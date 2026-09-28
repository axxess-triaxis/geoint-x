"""Transparent per-candidate value estimates for "where should the system look next?".

Adapted from the GALL-e-LEO / Agent Observer decision pipeline (candidate ->
per-candidate preview -> strategy -> optional LLM with allowlist -> deterministic
fallback), redesigned for satellite re-observation of monitored areas. Fixes
carried over from the audit of that code:

* every value term is counted exactly once (the unified strategy there added
  penalty-avoidance on top of an estimate that already contained it);
* the fairness term uses the fixed number of monitored districts, not the number
  observed so far (``len(done) or 8`` there);
* memory is built from reviewed outcomes (confirmed / rejected), not from what
  was merely chosen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from geointx.models import SceneRef

WEIGHTS = {
    "change_likelihood": 0.35,
    "staleness": 0.25,
    "urgency": 0.15,
    "coverage_fairness": 0.25,
}


@dataclass(frozen=True)
class Candidate:
    """A legal action: analyse ``next_scene`` for an AOI against ``prev_scene``."""

    aoi_id: str
    aoi_name: str
    mode: str
    district: str | None
    prev_scene: SceneRef
    next_scene: SceneRef
    cursor: datetime | None  # last observation already analysed (None: never analysed)
    megapixels: float
    target_revisit_days: int = 30

    @property
    def key(self) -> str:
        return f"{self.aoi_id}:{self.next_scene.scene_id}"


@dataclass(frozen=True)
class AreaMemory:
    alpha: float = 1.0  # 1 + confirmed cases
    beta: float = 1.0  # 1 + rejected cases
    recent_changed_ha_per_km2: float | None = None

    @property
    def confirm_rate(self) -> float:
        return self.alpha / (self.alpha + self.beta)


@dataclass
class Preview:
    candidate: Candidate
    terms: dict[str, float]
    p_usable: float
    cost: float
    value: float
    score: float
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        c = self.candidate
        return {
            "key": c.key,
            "aoi_id": c.aoi_id,
            "aoi_name": c.aoi_name,
            "district": c.district,
            "prev_scene_id": c.prev_scene.scene_id,
            "prev_date": c.prev_scene.datetime.date().isoformat(),
            "next_scene_id": c.next_scene.scene_id,
            "next_date": c.next_scene.datetime.date().isoformat(),
            "terms": {k: round(v, 4) for k, v in self.terms.items()},
            "weights": WEIGHTS,
            "p_usable": round(self.p_usable, 4),
            "cost": round(self.cost, 4),
            "value": round(self.value, 4),
            "score": round(self.score, 4),
            "notes": self.notes,
        }


def jain_index(counts: list[float]) -> float:
    s = sum(counts)
    sq = sum(x * x for x in counts)
    if sq == 0:
        return 0.0
    return (s * s) / (len(counts) * sq)


def fairness_gain(counts_by_district: dict[str, float], district: str | None) -> float:
    """Increase in Jain evenness if one more observation lands in ``district``.

    ``counts_by_district`` must contain every monitored district (zeros included),
    so the index is computed over the true number of districts from the start.
    """
    if district is None or district not in counts_by_district:
        return 0.0
    before = list(counts_by_district.values())
    after = [v + (1 if k == district else 0) for k, v in counts_by_district.items()]
    return max(0.0, jain_index(after) - jain_index(before))


def clear_sky_outlook(
    catalog: list[dict[str, object]], now: datetime, horizon_days: int = 60, max_cloud: float = 20.0
) -> tuple[float, int]:
    """Historical share of acquisitions with cloud <= max_cloud in the coming window.

    Uses the same calendar window in previous years of the real acquisition
    catalogue. Returns (share, sample size).
    """
    start_doy = now.timetuple().tm_yday
    hits = total = 0
    for row in catalog:
        dt = row["datetime"]
        assert isinstance(dt, datetime)
        if dt >= now:
            continue
        delta = (dt.timetuple().tm_yday - start_doy) % 366
        if delta <= horizon_days:
            total += 1
            cc = row.get("cloud_cover")
            if isinstance(cc, (int, float)) and cc <= max_cloud:
                hits += 1
    return (hits / total if total else 0.5), total


def preview(
    c: Candidate,
    memory: AreaMemory,
    now: datetime,
    outlook: float,
    counts_by_district: dict[str, float],
    mean_megapixels: float,
    cost_aware: bool = False,
) -> Preview:
    """Value estimate for one candidate.

    ``cost_aware`` divides by relative processing cost (area in megapixels). It is
    off by default: the scheduler backtest (docs/BACKTEST.md) showed that at these
    area sizes the cost term systematically starves the largest area and worsens
    coverage, while processing cost differences are negligible in practice.
    """
    notes: list[str] = []
    intensity = memory.recent_changed_ha_per_km2
    if intensity is None:
        change = memory.confirm_rate
        notes.append("No previous analysis: change likelihood from prior only.")
    else:
        change = 0.5 * memory.confirm_rate + 0.5 * min(1.0, intensity / 2.0)
    if c.cursor is None:
        staleness = 1.0
        notes.append("Never analysed: establishing a baseline comparison.")
    else:
        days = max(0.0, (now - c.cursor).total_seconds() / 86400)
        staleness = 1 - math.exp(-days / max(1, c.target_revisit_days))
    urgency = 1.0 - outlook
    fair = min(1.0, fairness_gain(counts_by_district, c.district) * 4)  # scale ~0..0.25 -> 0..1
    terms = {
        "change_likelihood": change,
        "staleness": staleness,
        "urgency": urgency,
        "coverage_fairness": fair,
    }
    value = sum(WEIGHTS[k] * v for k, v in terms.items())
    p_usable = c.next_scene.aoi_valid_fraction
    if p_usable is None:
        cc = c.next_scene.cloud_cover
        p_usable = 1 - (cc or 50.0) / 100
        notes.append("AOI clear fraction unknown: estimated from scene cloud cover.")
    cost = (c.megapixels / mean_megapixels) if cost_aware and mean_megapixels > 0 else 1.0
    score = value * p_usable / cost
    return Preview(c, terms, p_usable, cost, value, score, notes)
