"""Land-state and change-transition classification (heuristic v1).

This is a transparent, rule-based classifier over spectral indices, optionally
anchored to an external baseline land-cover map (ESA WorldCover). It is
indicative only: it has not been validated against ground truth for Assam, and
it is deliberately built behind the ``ChangeClassifier`` protocol so a trained
model can replace it without touching the rest of the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

ALGORITHM_VERSION = "rule-v1.0"


class LandState(IntEnum):
    NODATA = 0
    WATER = 1
    DENSE_VEG = 2
    SPARSE_VEG = 3
    NONVEG = 4  # bare soil, built-up, sand, rock -- not separable from indices alone


class Transition(IntEnum):
    NO_CHANGE = 0
    WATER_LOSS = 1
    WATER_GAIN = 2
    FOREST_CLEARING = 3
    CROPLAND_TO_BARE_OR_BUILT = 4
    VEGETATION_TO_BARE_OR_BUILT = 5
    WETLAND_VEGETATION_LOSS = 6
    REVEGETATION = 7


TRANSITION_LABELS: dict[Transition, str] = {
    Transition.WATER_LOSS: "Water to non-water",
    Transition.WATER_GAIN: "Non-water to water",
    Transition.FOREST_CLEARING: "Tree cover to bare/built-up",
    Transition.CROPLAND_TO_BARE_OR_BUILT: "Cropland to bare/built-up",
    Transition.VEGETATION_TO_BARE_OR_BUILT: "Vegetation to bare/built-up",
    Transition.WETLAND_VEGETATION_LOSS: "Wetland vegetation loss",
    Transition.REVEGETATION: "Bare to vegetation",
}

# ESA WorldCover class codes (v100/v200).
WC_TREE = 10
WC_SHRUB = 20
WC_GRASS = 30
WC_CROP = 40
WC_BUILT = 50
WC_BARE = 60
WC_WATER = 80
WC_WETLAND = 90
WC_MANGROVE = 95
WORLDCOVER_NAMES: dict[int, str] = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}
WETLAND_BASELINE = (WC_WATER, WC_WETLAND, WC_MANGROVE)


@dataclass(frozen=True)
class ClassifierParams:
    water_mndwi: float = 0.0
    water_max_ndvi: float = 0.2
    dense_veg_ndvi: float = 0.5
    sparse_veg_ndvi: float = 0.25
    min_water_delta: float = 0.2  # |dMNDWI| required for water loss/gain
    min_veg_loss: float = 0.2  # -dNDVI required for vegetation loss
    min_veg_gain: float = 0.25


def classify_state(
    ndvi: NDArray[np.float32],
    mndwi: NDArray[np.float32],
    valid: NDArray[np.bool_],
    p: ClassifierParams,
) -> NDArray[np.uint8]:
    state = np.full(ndvi.shape, LandState.NODATA, dtype=np.uint8)
    ok = valid & np.isfinite(ndvi) & np.isfinite(mndwi)
    water = ok & (mndwi > p.water_mndwi) & (ndvi < p.water_max_ndvi)
    dense = ok & ~water & (ndvi >= p.dense_veg_ndvi)
    sparse = ok & ~water & (ndvi >= p.sparse_veg_ndvi) & (ndvi < p.dense_veg_ndvi)
    nonveg = ok & ~water & (ndvi < p.sparse_veg_ndvi)
    state[water] = LandState.WATER
    state[dense] = LandState.DENSE_VEG
    state[sparse] = LandState.SPARSE_VEG
    state[nonveg] = LandState.NONVEG
    return state


class ChangeClassifier(Protocol):
    version: str

    def classify(
        self,
        idx_t1: dict[str, NDArray[np.float32]],
        idx_t2: dict[str, NDArray[np.float32]],
        valid: NDArray[np.bool_],
        baseline: NDArray[np.uint8] | None,
    ) -> tuple[NDArray[np.uint8], NDArray[np.uint8], NDArray[np.uint8]]:
        """Return (transition codes, state_t1, state_t2)."""
        ...


class RuleBasedClassifier:
    version = ALGORITHM_VERSION

    def __init__(self, params: ClassifierParams | None = None) -> None:
        self.params = params or ClassifierParams()

    def classify(
        self,
        idx_t1: dict[str, NDArray[np.float32]],
        idx_t2: dict[str, NDArray[np.float32]],
        valid: NDArray[np.bool_],
        baseline: NDArray[np.uint8] | None,
    ) -> tuple[NDArray[np.uint8], NDArray[np.uint8], NDArray[np.uint8]]:
        p = self.params
        s1 = classify_state(idx_t1["ndvi"], idx_t1["mndwi"], valid, p)
        s2 = classify_state(idx_t2["ndvi"], idx_t2["mndwi"], valid, p)
        d_ndvi = idx_t2["ndvi"] - idx_t1["ndvi"]
        d_mndwi = idx_t2["mndwi"] - idx_t1["mndwi"]
        both = (s1 != LandState.NODATA) & (s2 != LandState.NODATA)

        out = np.zeros(s1.shape, dtype=np.uint8)
        veg1 = (s1 == LandState.DENSE_VEG) | (s1 == LandState.SPARSE_VEG)

        water_loss = (
            both
            & (s1 == LandState.WATER)
            & (s2 != LandState.WATER)
            & (d_mndwi <= -p.min_water_delta)
        )
        water_gain = (
            both
            & (s1 != LandState.WATER)
            & (s2 == LandState.WATER)
            & (d_mndwi >= p.min_water_delta)
        )
        veg_loss = both & veg1 & (s2 == LandState.NONVEG) & (d_ndvi <= -p.min_veg_loss)
        reveg = (
            both
            & (s1 == LandState.NONVEG)
            & (s2 == LandState.DENSE_VEG)
            & (d_ndvi >= p.min_veg_gain)
        )

        out[water_loss] = Transition.WATER_LOSS
        out[water_gain] = Transition.WATER_GAIN
        out[reveg] = Transition.REVEGETATION
        if baseline is None:
            out[veg_loss] = Transition.VEGETATION_TO_BARE_OR_BUILT
        else:
            wet = np.isin(baseline, WETLAND_BASELINE)
            out[veg_loss & wet] = Transition.WETLAND_VEGETATION_LOSS
            out[veg_loss & (baseline == WC_TREE)] = Transition.FOREST_CLEARING
            out[veg_loss & (baseline == WC_CROP)] = Transition.CROPLAND_TO_BARE_OR_BUILT
            other = veg_loss & ~wet & (baseline != WC_TREE) & (baseline != WC_CROP)
            out[other] = Transition.VEGETATION_TO_BARE_OR_BUILT
        return out, s1, s2
