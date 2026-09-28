"""Turn per-pixel transition maps into discrete change regions (polygons)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from geointx.change.classify import Transition
from geointx.change.detect import ChangeResult

EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)


@dataclass(frozen=True)
class VectorizeParams:
    min_area_ha: float = 0.5  # minimum mapping unit
    opening_iterations: int = 1  # speckle removal; 0 disables


@dataclass
class ChangeRegion:
    transition: Transition
    mask: NDArray[np.bool_]  # full-grid boolean mask for this region
    pixel_count: int
    area_ha: float
    geometry_utm: BaseGeometry
    geometry_wgs84: BaseGeometry


def extract_regions(
    result: ChangeResult, params: VectorizeParams | None = None
) -> list[ChangeRegion]:
    p = params or VectorizeParams()
    grid = result.grid
    min_pixels = int(np.ceil(p.min_area_ha * 10_000 / grid.pixel_area_m2))
    regions: list[ChangeRegion] = []
    for code in np.unique(result.transitions):
        if code == Transition.NO_CHANGE:
            continue
        mask = result.transitions == code
        if p.opening_iterations > 0:
            # Square element: removes 1-2 px speckle/lines but keeps blobs >= 3x3 exact
            # (a cross element would also shave the corners off every real region).
            mask = ndimage.binary_opening(
                mask, structure=EIGHT_CONNECTED, iterations=p.opening_iterations
            )
        labels, n = ndimage.label(mask, structure=EIGHT_CONNECTED)
        if n == 0:
            continue
        sizes = ndimage.sum_labels(mask, labels, index=np.arange(1, n + 1))
        for lab, size in enumerate(sizes, start=1):
            if size < min_pixels:
                continue
            comp = labels == lab
            polys = [
                shape(geom)
                for geom, val in features.shapes(
                    comp.astype(np.uint8), mask=comp, transform=grid.transform, connectivity=8
                )
                if val == 1
            ]
            geom_utm = unary_union(polys)
            pixel_count = int(size)
            regions.append(
                ChangeRegion(
                    transition=Transition(int(code)),
                    mask=comp,
                    pixel_count=pixel_count,
                    area_ha=pixel_count * grid.pixel_area_m2 / 10_000,
                    geometry_utm=geom_utm,
                    geometry_wgs84=grid.to_wgs84(geom_utm),
                )
            )
    regions.sort(key=lambda r: r.area_ha, reverse=True)
    return regions
