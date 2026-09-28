"""End-to-end deterministic pipeline: observations -> change -> regions -> Findings.

Nothing in this module calls an LLM. Its output (``Finding``) is the only thing
the GenAI layer is allowed to interpret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from geointx.change.classify import (
    TRANSITION_LABELS,
    WORLDCOVER_NAMES,
    ClassifierParams,
    Transition,
    classify_state,
)
from geointx.change.confidence import persistence_fraction, score_confidence
from geointx.change.detect import ChangeResult, Observation, detect_change
from geointx.change.indices import compute_indices
from geointx.change.vectorize import ChangeRegion, VectorizeParams, extract_regions
from geointx.geo.overlap import MonitoredPolygon, compute_overlaps
from geointx.imagery import render
from geointx.models import EvidenceItem, Finding, TransitionName

TRANSITION_NAMES: dict[Transition, TransitionName] = {
    Transition.WATER_LOSS: "water_loss",
    Transition.WATER_GAIN: "water_gain",
    Transition.FOREST_CLEARING: "forest_clearing",
    Transition.CROPLAND_TO_BARE_OR_BUILT: "cropland_to_bare_or_built",
    Transition.VEGETATION_TO_BARE_OR_BUILT: "vegetation_to_bare_or_built",
    Transition.WETLAND_VEGETATION_LOSS: "wetland_vegetation_loss",
    Transition.REVEGETATION: "revegetation",
}


@dataclass
class AoiContext:
    aoi_id: str
    polygons: list[MonitoredPolygon] = field(default_factory=list)
    districts: list[tuple[str, BaseGeometry]] = field(default_factory=list)  # WGS84


@dataclass
class RunOutput:
    result: ChangeResult
    regions: list[ChangeRegion]
    findings: list[Finding]
    run_artifacts: list[EvidenceItem]


def _mean(arr: NDArray[np.float32], mask: NDArray[np.bool_]) -> float:
    vals = arr[mask]
    vals = vals[np.isfinite(vals)]
    return round(float(vals.mean()), 4) if vals.size else float("nan")


def _caveats(transition: Transition, region_overlaps_unofficial: list[str]) -> list[str]:
    c = [
        "Transition class comes from heuristic spectral rules (rule-v1.0); it is indicative and "
        "has not been validated against field data for this area.",
        "Detected change is a suspected change for human verification, not a legal finding.",
    ]
    if transition in (
        Transition.CROPLAND_TO_BARE_OR_BUILT,
        Transition.VEGETATION_TO_BARE_OR_BUILT,
        Transition.FOREST_CLEARING,
        Transition.WETLAND_VEGETATION_LOSS,
    ):
        c.append(
            "Bare soil and built-up surfaces cannot be separated from these spectral indices "
            "alone; seasonal fallow or harvest can look similar."
        )
    if transition in (Transition.WATER_LOSS, Transition.WATER_GAIN):
        c.append(
            "Water extent varies with season and rainfall; comparing dry-season scenes reduces "
            "but does not remove this effect."
        )
    for name in region_overlaps_unofficial:
        c.append(f"Boundary '{name}' is not an official record; overlap figures are indicative.")
    return c


def run_detection(
    *,
    run_id: str,
    t1: Observation,
    t2: Observation,
    later: list[Observation],
    baseline: NDArray[np.uint8] | None,
    ctx: AoiContext,
    artifact_dir: Path | None = None,
    artifact_url_prefix: str = "",
    vectorize_params: VectorizeParams | None = None,
) -> RunOutput:
    result = detect_change(t1, t2, baseline)
    regions = extract_regions(result, vectorize_params)
    cparams = ClassifierParams()
    later_states = []
    for obs in later:
        idx = compute_indices(obs.bands)
        later_states.append(classify_state(idx["ndvi"], idx["mndwi"], obs.valid, cparams))

    run_artifacts: list[EvidenceItem] = []
    tc1 = tc2 = None
    if artifact_dir is not None:
        tc1 = render.true_color(t1.bands, t1.valid)
        tc2 = render.true_color(t2.bands, t2.valid)
        for kind, arr, name, desc in (
            ("image_before", tc1, "before.png", f"True colour, {t1.scene.scene_id}"),
            ("image_after", tc2, "after.png", f"True colour, {t2.scene.scene_id}"),
            (
                "change_mask",
                render.transition_rgba(result.transitions),
                "change_mask.png",
                "Per-pixel transition map (all classes, before minimum-area filter)",
            ),
        ):
            sha = render.write_png(arr, artifact_dir / name)
            run_artifacts.append(
                EvidenceItem(
                    id=f"{run_id}:{name}",
                    kind=kind,  # type: ignore[arg-type]
                    description=desc,
                    uri=f"{artifact_url_prefix}/{name}",
                    sha256=sha,
                )
            )

    polys_by_id = {p.id: p for p in ctx.polygons}
    findings: list[Finding] = []
    for n, region in enumerate(regions, start=1):
        fid = f"{run_id}-F{n:03d}"
        m = region.mask
        means1 = {k: _mean(v, m) for k, v in result.idx_t1.items()}
        means2 = {k: _mean(v, m) for k, v in result.idx_t2.items()}
        deltas = {k: round(means2[k] - means1[k], 4) for k in means1}
        base_px = baseline[m] if baseline is not None else None
        base_share: dict[str, float] = {}
        if base_px is not None:
            codes, counts = np.unique(base_px, return_counts=True)
            for code, cnt in zip(codes, counts, strict=True):
                base_share[WORLDCOVER_NAMES.get(int(code), f"class {int(code)}")] = round(
                    float(cnt / base_px.size), 3
                )
        persist = persistence_fraction(m, result.state_t2, later_states) if later_states else None
        conf, factors = score_confidence(
            region.transition,
            region.pixel_count,
            deltas,
            t1.valid_fraction,
            t2.valid_fraction,
            base_px,
            persist,
        )
        overlaps = compute_overlaps(region.geometry_utm, ctx.polygons, result.grid)
        unofficial = [o.polygon_name for o in overlaps if not polys_by_id[o.polygon_id].official]
        centroid = region.geometry_wgs84.centroid
        district = next((name for name, geom in ctx.districts if geom.contains(centroid)), None)

        evidence: list[EvidenceItem] = [
            EvidenceItem(
                id=f"{fid}:scenes",
                kind="scene_metadata",
                description=(
                    f"T1 {t1.scene.scene_id} ({t1.scene.datetime:%Y-%m-%d}), "
                    f"T2 {t2.scene.scene_id} ({t2.scene.datetime:%Y-%m-%d})"
                ),
                uri=t2.scene.source_href,
            )
        ]
        if tc1 is not None and tc2 is not None and artifact_dir is not None:
            r0, r1, c0, c1 = render.crop_window(m)
            outline = render.region_outline_rgba(m[r0:r1, c0:c1])
            crops = (
                ("image_before", tc1[r0:r1, c0:c1], "before", "T1 true colour (crop)"),
                ("image_after", tc2[r0:r1, c0:c1], "after", "T2 true colour (crop)"),
                (
                    "change_mask",
                    render.overlay(tc2[r0:r1, c0:c1], outline),
                    "mask",
                    "Detected region outlined on T2",
                ),
            )
            for kind, arr, stem, desc in crops:
                name = f"{fid}_{stem}.png"
                sha = render.write_png(arr, artifact_dir / name, upscale=3)
                evidence.append(
                    EvidenceItem(
                        id=f"{fid}:{stem}",
                        kind=kind,  # type: ignore[arg-type]
                        description=desc,
                        uri=f"{artifact_url_prefix}/{name}",
                        sha256=sha,
                    )
                )
        if base_share:
            evidence.append(
                EvidenceItem(
                    id=f"{fid}:baseline",
                    kind="baseline_landcover",
                    description="ESA WorldCover baseline class shares: "
                    + ", ".join(f"{k} {v:.0%}" for k, v in base_share.items()),
                )
            )
        for o in overlaps:
            evidence.append(
                EvidenceItem(
                    id=f"{fid}:boundary:{o.polygon_id}",
                    kind="boundary",
                    description=(
                        f"{o.polygon_name} ({o.polygon_kind}, source: "
                        f"{polys_by_id[o.polygon_id].source})"
                    ),
                )
            )
        if persist is not None:
            evidence.append(
                EvidenceItem(
                    id=f"{fid}:history",
                    kind="temporal_history",
                    description=(
                        f"Persistence across {len(later)} later observation(s): {persist:.0%}"
                    ),
                )
            )

        findings.append(
            Finding(
                id=fid,
                run_id=run_id,
                aoi_id=ctx.aoi_id,
                transition=TRANSITION_NAMES[region.transition],
                transition_label=TRANSITION_LABELS[region.transition],
                geometry=dict(mapping(region.geometry_wgs84)),
                centroid=(round(centroid.x, 6), round(centroid.y, 6)),
                area_ha=round(region.area_ha, 3),
                pixel_count=region.pixel_count,
                t1=t1.scene,
                t2=t2.scene,
                index_means_t1=means1,
                index_means_t2=means2,
                index_deltas=deltas,
                baseline_landcover=base_share,
                persistence=None if persist is None else round(persist, 3),
                confidence=conf,
                confidence_factors=factors,
                overlaps=overlaps,
                district=district,
                algorithm_version=result.algorithm_version,
                evidence=evidence,
                caveats=_caveats(region.transition, unofficial),
            )
        )
    return RunOutput(result=result, regions=regions, findings=findings, run_artifacts=run_artifacts)
