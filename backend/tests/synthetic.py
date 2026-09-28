"""Synthetic observations with exactly known surfaces, for golden tests."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from geointx.change.detect import Observation
from geointx.geo.grid import GridSpec
from geointx.models import SceneRef

GRID = GridSpec(
    epsg=32646, origin_x=360_000.0, origin_y=2_890_000.0, pixel_size=10.0, width=200, height=200
)

# Representative surface reflectances (blue, green, red, nir, swir16).
SURFACES: dict[str, tuple[float, float, float, float, float]] = {
    "veg": (0.04, 0.07, 0.04, 0.35, 0.18),  # NDVI ~0.80, MNDWI ~-0.44
    "bare": (0.11, 0.13, 0.15, 0.20, 0.25),  # NDVI ~0.14, MNDWI ~-0.32
    "water": (0.05, 0.06, 0.03, 0.02, 0.01),  # NDVI -0.20, MNDWI ~0.71
}
CODES = {"veg": 1, "bare": 2, "water": 3}
BAND_ORDER = ("blue", "green", "red", "nir", "swir16")


def surface_map(fill: str = "veg") -> NDArray[np.uint8]:
    return np.full((GRID.height, GRID.width), CODES[fill], dtype=np.uint8)


def observation(
    surfaces: NDArray[np.uint8],
    when: datetime,
    scene_id: str,
    cloud: NDArray[np.bool_] | None = None,
) -> Observation:
    bands: dict[str, NDArray[np.float32]] = {
        b: np.zeros(surfaces.shape, dtype=np.float32) for b in BAND_ORDER
    }
    for name, code in CODES.items():
        m = surfaces == code
        for b, val in zip(BAND_ORDER, SURFACES[name], strict=True):
            bands[b][m] = val
    valid = np.ones(surfaces.shape, dtype=bool) if cloud is None else ~cloud
    return Observation(
        scene=SceneRef(scene_id=scene_id, collection="synthetic", datetime=when),
        grid=GRID,
        bands=bands,
        valid=valid,
    )


T1 = datetime(2020, 1, 15, tzinfo=UTC)
T2 = datetime(2025, 1, 15, tzinfo=UTC)
T3 = datetime(2025, 2, 15, tzinfo=UTC)
