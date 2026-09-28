"""Deterministic confidence scoring for a change region.

This is a heuristic evidence-strength score in [0, 1], not a calibrated
probability. Each factor is reported so a reviewer can see why a score is high
or low.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from geointx.change.classify import WETLAND_BASELINE, LandState, Transition
from geointx.models import ConfidenceFactor

# The index whose change defines each transition, and the delta that counts as "strong".
_PRIMARY_INDEX: dict[Transition, tuple[str, float]] = {
    Transition.WATER_LOSS: ("mndwi", 0.5),
    Transition.WATER_GAIN: ("mndwi", 0.5),
    Transition.FOREST_CLEARING: ("ndvi", 0.45),
    Transition.CROPLAND_TO_BARE_OR_BUILT: ("ndvi", 0.45),
    Transition.VEGETATION_TO_BARE_OR_BUILT: ("ndvi", 0.45),
    Transition.WETLAND_VEGETATION_LOSS: ("ndvi", 0.45),
    Transition.REVEGETATION: ("ndvi", 0.45),
}

# Baseline classes consistent with the *starting* state of each transition.
_BASELINE_CONSISTENT: dict[Transition, tuple[int, ...]] = {
    Transition.WATER_LOSS: WETLAND_BASELINE,
    Transition.WATER_GAIN: (10, 20, 30, 40, 50, 60, 90),
    Transition.FOREST_CLEARING: (10,),
    Transition.CROPLAND_TO_BARE_OR_BUILT: (40,),
    Transition.VEGETATION_TO_BARE_OR_BUILT: (10, 20, 30, 40, 90, 95),
    Transition.WETLAND_VEGETATION_LOSS: WETLAND_BASELINE,
    Transition.REVEGETATION: (40, 50, 60),
}

WEIGHTS = {
    "signal_strength": 0.30,
    "observation_quality": 0.20,
    "region_size": 0.15,
    "baseline_agreement": 0.15,
    "persistence": 0.20,
}


def _clamp(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def persistence_fraction(
    mask: NDArray[np.bool_],
    state_t2: NDArray[np.uint8],
    later_states: list[NDArray[np.uint8]],
) -> float | None:
    """Share of region pixels (clear in the later scene) still in their T2 state."""
    kept = 0
    seen = 0
    for later in later_states:
        clear = mask & (later != LandState.NODATA)
        n = int(clear.sum())
        if n == 0:
            continue
        # Dense/sparse vegetation are both "vegetated" for persistence purposes.
        a = _collapse(state_t2[clear])
        b = _collapse(later[clear])
        kept += int((a == b).sum())
        seen += n
    if seen == 0:
        return None
    return kept / seen


def _collapse(s: NDArray[np.uint8]) -> NDArray[np.uint8]:
    out = s.copy()
    out[out == LandState.SPARSE_VEG] = LandState.DENSE_VEG
    return out


def score_confidence(
    transition: Transition,
    pixel_count: int,
    mean_delta: dict[str, float],
    t1_valid_fraction: float,
    t2_valid_fraction: float,
    baseline_pixels: NDArray[np.uint8] | None,
    persistence: float | None,
) -> tuple[float, list[ConfidenceFactor]]:
    idx_name, strong = _PRIMARY_INDEX[transition]
    delta = abs(mean_delta.get(idx_name, 0.0))
    factors: list[ConfidenceFactor] = [
        ConfidenceFactor(
            name="signal_strength",
            value=_clamp(delta / strong),
            weight=WEIGHTS["signal_strength"],
            explanation=f"Mean |d{idx_name.upper()}| = {delta:.3f} (strong at >= {strong}).",
        ),
        ConfidenceFactor(
            name="observation_quality",
            value=_clamp(min(t1_valid_fraction, t2_valid_fraction)),
            weight=WEIGHTS["observation_quality"],
            explanation=(
                f"Clear-sky share of AOI: T1 {t1_valid_fraction:.0%}, T2 {t2_valid_fraction:.0%}."
            ),
        ),
        ConfidenceFactor(
            name="region_size",
            value=_clamp(pixel_count / 500.0),
            weight=WEIGHTS["region_size"],
            explanation=f"{pixel_count} pixels; regions >= 500 px (5 ha) score fully.",
        ),
    ]
    if baseline_pixels is not None and baseline_pixels.size:
        consistent = float(np.isin(baseline_pixels, _BASELINE_CONSISTENT[transition]).mean())
        factors.append(
            ConfidenceFactor(
                name="baseline_agreement",
                value=consistent,
                weight=WEIGHTS["baseline_agreement"],
                explanation=(
                    f"{consistent:.0%} of pixels had a baseline land-cover class consistent "
                    "with the starting state (ESA WorldCover)."
                ),
            )
        )
    if persistence is not None:
        factors.append(
            ConfidenceFactor(
                name="persistence",
                value=_clamp(persistence),
                weight=WEIGHTS["persistence"],
                explanation=(
                    f"{persistence:.0%} of pixels remained in the changed state in later "
                    "observations."
                ),
            )
        )
    total_w = sum(f.weight for f in factors)
    score = sum(f.value * f.weight for f in factors) / total_w
    return round(score, 3), factors
