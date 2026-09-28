"""Spatial relationship between a change region and monitored boundaries.

All measurement happens in the AOI's UTM projection, so areas and distances are
in real metres, not degrees.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from geointx.geo.grid import GridSpec
from geointx.models import OverlapInfo

POLYGON_KINDS = ("wetland", "protected_area", "government_land", "water_body", "other")


@dataclass(frozen=True)
class MonitoredPolygon:
    id: str
    name: str
    kind: str
    geometry_wgs84: BaseGeometry
    source: str
    official: bool = False
    buffer_m: float = 200.0  # eco-sensitive / watch buffer around the boundary


def compute_overlaps(
    region_utm: BaseGeometry, polygons: list[MonitoredPolygon], grid: GridSpec
) -> list[OverlapInfo]:
    out: list[OverlapInfo] = []
    region_area = region_utm.area
    if region_area <= 0:
        return out
    for poly in polygons:
        p_utm = grid.from_wgs84(poly.geometry_wgs84)
        if not p_utm.is_valid:
            p_utm = p_utm.buffer(0)
        inter = region_utm.intersection(p_utm)
        inside_frac = inter.area / region_area
        distance = region_utm.distance(p_utm.boundary) if inside_frac < 1.0 else 0.0
        if inside_frac == 0.0:
            distance = region_utm.distance(p_utm)
        within_buffer = inside_frac == 0.0 and distance <= poly.buffer_m
        if inside_frac == 0.0 and not within_buffer:
            continue
        out.append(
            OverlapInfo(
                polygon_id=poly.id,
                polygon_name=poly.name,
                polygon_kind=poly.kind,
                overlap_ha=round(inter.area / 10_000, 4),
                fraction_of_finding_inside=round(inside_frac, 4),
                crosses_boundary=0.0 < inside_frac < 1.0,
                within_buffer=within_buffer,
                distance_to_boundary_m=round(float(distance), 1),
            )
        )
    return out
