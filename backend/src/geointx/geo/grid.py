"""Fixed analysis grids.

Every monitored area is analysed on one fixed UTM grid so that observations from
different dates line up pixel for pixel. Change detection never compares rasters
that are not on the same grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from affine import Affine
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform


def utm_epsg_for(lon: float, lat: float) -> int:
    zone = math.floor((lon + 180.0) / 6.0) + 1
    return (32600 if lat >= 0 else 32700) + zone


@dataclass(frozen=True)
class GridSpec:
    """A north-up raster grid in a projected CRS with square pixels (metres)."""

    epsg: int
    origin_x: float  # left edge
    origin_y: float  # top edge
    pixel_size: float
    width: int
    height: int

    @property
    def crs(self) -> CRS:
        return CRS.from_epsg(self.epsg)

    @property
    def transform(self) -> Affine:
        return Affine(self.pixel_size, 0.0, self.origin_x, 0.0, -self.pixel_size, self.origin_y)

    @property
    def pixel_area_m2(self) -> float:
        return self.pixel_size * self.pixel_size

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (
            self.origin_x,
            self.origin_y - self.height * self.pixel_size,
            self.origin_x + self.width * self.pixel_size,
            self.origin_y,
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "epsg": self.epsg,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "pixel_size": self.pixel_size,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, d: dict[str, float | int]) -> GridSpec:
        return cls(
            epsg=int(d["epsg"]),
            origin_x=float(d["origin_x"]),
            origin_y=float(d["origin_y"]),
            pixel_size=float(d["pixel_size"]),
            width=int(d["width"]),
            height=int(d["height"]),
        )

    @classmethod
    def from_lonlat_bbox(
        cls, bbox: tuple[float, float, float, float], pixel_size: float = 10.0
    ) -> GridSpec:
        """Build a grid covering a lon/lat bbox, snapped to whole pixels in UTM."""
        min_lon, min_lat, max_lon, max_lat = bbox
        epsg = utm_epsg_for((min_lon + max_lon) / 2, (min_lat + max_lat) / 2)
        to_utm = Transformer.from_crs(4326, epsg, always_xy=True)
        xs, ys = to_utm.transform(
            [min_lon, min_lon, max_lon, max_lon], [min_lat, max_lat, min_lat, max_lat]
        )
        left = math.floor(min(xs) / pixel_size) * pixel_size
        right = math.ceil(max(xs) / pixel_size) * pixel_size
        bottom = math.floor(min(ys) / pixel_size) * pixel_size
        top = math.ceil(max(ys) / pixel_size) * pixel_size
        return cls(
            epsg=epsg,
            origin_x=left,
            origin_y=top,
            pixel_size=pixel_size,
            width=round((right - left) / pixel_size),
            height=round((top - bottom) / pixel_size),
        )

    def lonlat_bounds(self) -> tuple[float, float, float, float]:
        poly = self.to_wgs84(box(*self.bounds))
        minx, miny, maxx, maxy = poly.bounds
        return (minx, miny, maxx, maxy)

    def to_wgs84(self, geom: BaseGeometry) -> BaseGeometry:
        t = Transformer.from_crs(self.epsg, 4326, always_xy=True)
        return shp_transform(t.transform, geom)

    def from_wgs84(self, geom: BaseGeometry) -> BaseGeometry:
        t = Transformer.from_crs(4326, self.epsg, always_xy=True)
        return shp_transform(t.transform, geom)


def geojson_to_shape(geojson: dict[str, object]) -> BaseGeometry:
    return shape(geojson)


def shape_to_geojson(geom: BaseGeometry) -> dict[str, object]:
    return dict(mapping(geom))


def bbox_polygon(bbox: tuple[float, float, float, float]) -> Polygon:
    return box(*bbox)
