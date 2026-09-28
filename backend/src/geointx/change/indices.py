"""Spectral indices computed from surface reflectance (0..1 floats).

All functions are pure numpy; NaN marks pixels where the index is undefined.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

F32 = NDArray[np.float32]


def normalized_difference(a: F32, b: F32) -> F32:
    """(a - b) / (a + b), NaN where the denominator is ~0 or inputs are NaN."""
    a64 = a.astype(np.float64)
    b64 = b.astype(np.float64)
    denom = a64 + b64
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(denom) > 1e-6, (a64 - b64) / denom, np.nan)
    return out.astype(np.float32)


def ndvi(nir: F32, red: F32) -> F32:
    """Normalized Difference Vegetation Index (Rouse et al., 1974)."""
    return normalized_difference(nir, red)


def mndwi(green: F32, swir16: F32) -> F32:
    """Modified Normalized Difference Water Index (Xu, 2006)."""
    return normalized_difference(green, swir16)


def ndbi(swir16: F32, nir: F32) -> F32:
    """Normalized Difference Built-up Index (Zha et al., 2003).

    NDBI responds to built-up surfaces but also to bare soil; it is used here as a
    supporting signal, never as a standalone built-up classifier.
    """
    return normalized_difference(swir16, nir)


def compute_indices(bands: dict[str, F32]) -> dict[str, F32]:
    return {
        "ndvi": ndvi(bands["nir"], bands["red"]),
        "mndwi": mndwi(bands["green"], bands["swir16"]),
        "ndbi": ndbi(bands["swir16"], bands["nir"]),
    }
