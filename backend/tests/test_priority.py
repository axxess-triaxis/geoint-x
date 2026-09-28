from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geointx.models import Finding, OverlapInfo, SceneRef
from geointx.priority.engine import WEIGHTS, prioritise


def _finding(**kw: object) -> Finding:
    scene = SceneRef(scene_id="s", collection="c", datetime=datetime(2025, 1, 1, tzinfo=UTC))
    base: dict[str, object] = dict(
        id="R-F001",
        run_id="R",
        aoi_id="a",
        transition="wetland_vegetation_loss",
        transition_label="Wetland vegetation loss",
        geometry={"type": "Point", "coordinates": [0, 0]},
        centroid=(0.0, 0.0),
        area_ha=4.0,
        pixel_count=400,
        t1=scene,
        t2=scene,
        index_means_t1={},
        index_means_t2={},
        index_deltas={},
        confidence=0.8,
        confidence_factors=[],
        algorithm_version="rule-v1.0",
    )
    base.update(kw)
    return Finding.model_validate(base)


def _inside(frac: float) -> OverlapInfo:
    return OverlapInfo(
        polygon_id="w",
        polygon_name="Wetland",
        polygon_kind="wetland",
        overlap_ha=frac * 4,
        fraction_of_finding_inside=frac,
        crosses_boundary=0 < frac < 1,
        within_buffer=False,
        distance_to_boundary_m=0,
    )


def test_breakdown_sums_to_score_and_is_deterministic() -> None:
    f = _finding(overlaps=[_inside(1.0)])
    a, b = prioritise(f), prioritise(f)
    assert a == b
    assert a.score == pytest.approx(sum(x.contribution for x in a.factors), abs=0.05)
    assert {x.name for x in a.factors} == set(WEIGHTS)
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_inside_protected_boundary_outranks_outside() -> None:
    inside = prioritise(_finding(overlaps=[_inside(1.0)]))
    outside = prioritise(_finding())
    assert inside.score > outside.score
    assert inside.band == "P1"


def test_history_raises_or_lowers_priority() -> None:
    f = _finding()
    assert prioritise(f, 0.9).score > prioritise(f, None).score > prioritise(f, 0.1).score


def test_revegetation_is_low_priority() -> None:
    assert prioritise(_finding(transition="revegetation", confidence=0.5)).band == "P3"


def test_transient_change_ranks_below_persistent_change() -> None:
    lasting = prioritise(_finding(overlaps=[_inside(1.0)], persistence=0.9))
    transient = prioritise(_finding(overlaps=[_inside(1.0)], persistence=0.0))
    assert lasting.score - transient.score == pytest.approx(18.0, abs=0.1)
    assert transient.band != "P1"
    assert "transient" in next(f for f in transient.factors if f.name == "persistence").explanation


def test_water_gain_inside_wetland_gets_half_boundary_weight() -> None:
    loss = prioritise(_finding(transition="water_loss", overlaps=[_inside(1.0)]))
    gain = prioritise(_finding(transition="water_gain", overlaps=[_inside(1.0)]))
    ctx = {r.band: next(f for f in r.factors if f.name == "boundary_context") for r in (loss, gain)}
    assert gain.score < loss.score
    assert any("Halved" in f.explanation for f in ctx.values())
