"""Golden tests: injected changes with known size must be recovered exactly."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box

from geointx.change.classify import Transition
from geointx.change.detect import detect_change
from geointx.change.vectorize import extract_regions
from geointx.geo.overlap import MonitoredPolygon
from geointx.pipeline import AoiContext, run_detection
from tests.synthetic import GRID, T1, T2, T3, observation, surface_map


def test_vegetation_to_bare_block_recovered_exactly() -> None:
    before = surface_map("veg")
    after = before.copy()
    after[50:70, 100:130] = 2  # 20 x 30 px = 600 px = 6.00 ha
    res = detect_change(observation(before, T1, "a"), observation(after, T2, "b"))
    regions = extract_regions(res)
    assert len(regions) == 1
    r = regions[0]
    assert r.transition == Transition.VEGETATION_TO_BARE_OR_BUILT
    assert r.pixel_count == 600
    assert r.area_ha == pytest.approx(6.0)
    assert r.geometry_utm.area == pytest.approx(60_000.0)


def test_water_loss_and_minimum_mapping_unit() -> None:
    before = surface_map("veg")
    before[10:20, 10:20] = 3  # 1.00 ha of water
    before[150:155, 150:155] = 3  # 0.25 ha of water, below the 0.5 ha MMU
    after = surface_map("veg")
    after[10:20, 10:20] = 2
    after[150:155, 150:155] = 2
    res = detect_change(observation(before, T1, "a"), observation(after, T2, "b"))
    regions = extract_regions(res)
    assert [(r.transition, r.pixel_count) for r in regions] == [(Transition.WATER_LOSS, 100)]


def test_baseline_landcover_subtypes_vegetation_loss() -> None:
    before = surface_map("veg")
    after = before.copy()
    after[20:40, 20:40] = 2
    after[120:140, 120:140] = 2
    baseline = np.full(before.shape, 40, dtype=np.uint8)  # cropland
    baseline[0:100, 0:100] = 10  # tree cover
    baseline[100:200, 100:200] = 90  # herbaceous wetland
    res = detect_change(observation(before, T1, "a"), observation(after, T2, "b"), baseline)
    kinds = sorted(r.transition for r in extract_regions(res))
    assert kinds == [Transition.FOREST_CLEARING, Transition.WETLAND_VEGETATION_LOSS]


def test_cloud_masked_change_is_not_reported() -> None:
    before = surface_map("veg")
    after = before.copy()
    after[50:70, 50:70] = 2
    cloud = np.zeros(before.shape, dtype=bool)
    cloud[40:80, 40:80] = True
    res = detect_change(observation(before, T1, "a"), observation(after, T2, "b", cloud))
    assert extract_regions(res) == []
    assert res.stats["valid_fraction"] == pytest.approx(1 - 1600 / 40_000)


def test_ordering_and_grid_checks() -> None:
    a = observation(surface_map(), T2, "a")
    b = observation(surface_map(), T1, "b")
    with pytest.raises(ValueError, match="earlier"):
        detect_change(a, b)


def test_pipeline_overlap_persistence_and_provenance() -> None:
    before = surface_map("veg")
    after = before.copy()
    after[50:70, 100:130] = 2  # 6 ha
    later = before.copy()
    later[50:70, 100:115] = 2  # half the region still bare, half re-vegetated
    # Monitored polygon covering exactly the left half of the region (cols 100..115).
    x0, y_top = GRID.origin_x, GRID.origin_y
    poly_utm = box(x0 + 1000, y_top - 700, x0 + 1150, y_top - 500)
    ctx = AoiContext(
        aoi_id="test",
        polygons=[
            MonitoredPolygon(
                id="w1",
                name="Test wetland",
                kind="wetland",
                geometry_wgs84=GRID.to_wgs84(poly_utm),
                source="synthetic",
            )
        ],
    )
    out = run_detection(
        run_id="R1",
        t1=observation(before, T1, "s1"),
        t2=observation(after, T2, "s2"),
        later=[observation(later, T3, "s3")],
        baseline=None,
        ctx=ctx,
    )
    assert len(out.findings) == 1
    f = out.findings[0]
    assert f.id == "R1-F001"
    assert f.area_ha == pytest.approx(6.0)
    assert f.t1.scene_id == "s1" and f.t2.scene_id == "s2"
    assert f.persistence == pytest.approx(0.5)
    assert len(f.overlaps) == 1
    o = f.overlaps[0]
    assert o.fraction_of_finding_inside == pytest.approx(0.5, abs=1e-3)
    assert o.overlap_ha == pytest.approx(3.0, abs=1e-2)
    assert o.crosses_boundary
    assert f.index_deltas["ndvi"] < -0.5
    assert 0 < f.confidence <= 1
    assert any("not an official record" in c for c in f.caveats)
    assert {e.kind for e in f.evidence} >= {"scene_metadata", "boundary", "temporal_history"}
