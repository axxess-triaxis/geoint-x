"""Dual-date change detection on a shared analysis grid."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from geointx.change.classify import ChangeClassifier, RuleBasedClassifier
from geointx.change.indices import compute_indices
from geointx.geo.grid import GridSpec
from geointx.models import SceneRef

# Sentinel-2 Scene Classification Layer values considered clear land/water.
SCL_CLEAR = (4, 5, 6, 7, 11)  # vegetation, not-vegetated, water, unclassified, snow

REQUIRED_BANDS = ("blue", "green", "red", "nir", "swir16")


@dataclass
class Observation:
    """One scene resampled onto an AOI grid. Reflectance as float32 0..1."""

    scene: SceneRef
    grid: GridSpec
    bands: dict[str, NDArray[np.float32]]
    valid: NDArray[np.bool_]

    def __post_init__(self) -> None:
        missing = [b for b in REQUIRED_BANDS if b not in self.bands]
        if missing:
            raise ValueError(f"observation missing bands: {missing}")
        shape = (self.grid.height, self.grid.width)
        for name, arr in self.bands.items():
            if arr.shape != shape:
                raise ValueError(f"band {name} shape {arr.shape} != grid {shape}")
        if self.valid.shape != shape:
            raise ValueError("valid mask shape does not match grid")

    @property
    def valid_fraction(self) -> float:
        return float(self.valid.mean())


def valid_from_scl(scl: NDArray[np.integer]) -> NDArray[np.bool_]:
    return np.isin(scl, SCL_CLEAR)


@dataclass
class ChangeResult:
    grid: GridSpec
    t1: Observation
    t2: Observation
    transitions: NDArray[np.uint8]
    state_t1: NDArray[np.uint8]
    state_t2: NDArray[np.uint8]
    valid: NDArray[np.bool_]
    idx_t1: dict[str, NDArray[np.float32]]
    idx_t2: dict[str, NDArray[np.float32]]
    baseline: NDArray[np.uint8] | None
    algorithm_version: str
    stats: dict[str, float] = field(default_factory=dict)


def detect_change(
    t1: Observation,
    t2: Observation,
    baseline: NDArray[np.uint8] | None = None,
    classifier: ChangeClassifier | None = None,
) -> ChangeResult:
    if t1.grid != t2.grid:
        raise ValueError("observations are not on the same analysis grid")
    if t1.scene.datetime >= t2.scene.datetime:
        raise ValueError("t1 must be earlier than t2")
    if baseline is not None and baseline.shape != t1.valid.shape:
        raise ValueError("baseline land cover not on analysis grid")
    clf = classifier or RuleBasedClassifier()
    valid = t1.valid & t2.valid
    idx1 = compute_indices(t1.bands)
    idx2 = compute_indices(t2.bands)
    transitions, s1, s2 = clf.classify(idx1, idx2, valid, baseline)
    changed = transitions > 0
    stats = {
        "valid_fraction": float(valid.mean()),
        "changed_pixels": float(changed.sum()),
        "changed_fraction_of_valid": float(changed.sum()) / max(int(valid.sum()), 1),
    }
    return ChangeResult(
        grid=t1.grid,
        t1=t1,
        t2=t2,
        transitions=transitions,
        state_t1=s1,
        state_t2=s2,
        valid=valid,
        idx_t1=idx1,
        idx_t2=idx2,
        baseline=baseline,
        algorithm_version=clf.version,
        stats=stats,
    )
