"""Live access to public Sentinel-2 L2A (Collection 1) and ESA WorldCover.

Sources (no authentication required):
- Element 84 Earth Search STAC: https://earth-search.aws.element84.com/v1
  collection ``sentinel-2-c1-l2a`` (harmonised reflectance, scale 1e-4, offset -0.1)
- ESA WorldCover 10 m (2020 v100, 2021 v200) COGs on AWS open data.

Every read is resampled onto the AOI's fixed ``GridSpec`` so observations from
different dates align pixel for pixel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import rasterio
from numpy.typing import NDArray
from pystac import Item
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from shapely.geometry import box, shape

from geointx.geo.grid import GridSpec
from geointx.models import SceneRef

EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1"
S2_COLLECTION = "sentinel-2-c1-l2a"
S2_BANDS = ("blue", "green", "red", "nir", "swir16", "scl")
S2_SCALE = 1e-4
S2_OFFSET = -0.1

WORLDCOVER_URLS = {
    2020: "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/ESA_WorldCover_10m_2020_v100_{tile}_Map.tif",
    2021: "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif",
}

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
}


@dataclass
class CatalogEntry:
    item: Item
    scene: SceneRef
    contains_aoi: bool


def open_client() -> Client:
    return Client.open(EARTH_SEARCH_URL)


def scene_ref(item: Item) -> SceneRef:
    dt = item.datetime
    assert dt is not None
    return SceneRef(
        scene_id=item.id,
        collection=S2_COLLECTION,
        datetime=dt,
        cloud_cover=item.properties.get("eo:cloud_cover"),
        platform=item.properties.get("platform"),
        source_href=f"{EARTH_SEARCH_URL}/collections/{S2_COLLECTION}/items/{item.id}",
    )


def search_scenes(
    bbox: tuple[float, float, float, float],
    start: datetime | str,
    end: datetime | str,
    max_cloud: float = 100.0,
    client: Client | None = None,
) -> list[CatalogEntry]:
    c = client or open_client()
    s = c.search(
        collections=[S2_COLLECTION],
        bbox=list(bbox),
        datetime=[start, end],
        query={"eo:cloud_cover": {"lte": max_cloud}},
        max_items=1000,
    )
    aoi = box(*bbox)
    out = []
    for item in s.items():
        geom = shape(item.geometry) if item.geometry else None
        out.append(
            CatalogEntry(
                item=item, scene=scene_ref(item), contains_aoi=bool(geom and geom.contains(aoi))
            )
        )
    out.sort(key=lambda e: e.scene.datetime)
    return out


def _read_to_grid(href: str, grid: GridSpec, resampling: Resampling, dtype: str) -> NDArray:
    with (
        rasterio.Env(**GDAL_ENV),
        rasterio.open(href) as src,
        WarpedVRT(
            src,
            crs=grid.crs,
            transform=grid.transform,
            width=grid.width,
            height=grid.height,
            resampling=resampling,
            nodata=0,
        ) as vrt,
    ):
        return vrt.read(1).astype(dtype)


def read_scene_dn(
    item: Item, grid: GridSpec, bands: tuple[str, ...] = S2_BANDS
) -> dict[str, NDArray]:
    """Read raw digital numbers (uint16; SCL uint8) for bands onto the grid."""
    out: dict[str, NDArray] = {}
    for b in bands:
        href = item.assets[b].href
        if b == "scl":
            out[b] = _read_to_grid(href, grid, Resampling.nearest, "uint8")
        else:
            out[b] = _read_to_grid(href, grid, Resampling.bilinear, "uint16")
    return out


def dn_to_reflectance(dn: NDArray) -> NDArray[np.float32]:
    refl = dn.astype(np.float32) * S2_SCALE + S2_OFFSET
    refl[dn == 0] = np.nan
    return refl


def _worldcover_tile(lon: float, lat: float) -> str:
    lat0 = int(math.floor(lat / 3.0) * 3)
    lon0 = int(math.floor(lon / 3.0) * 3)
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


def read_worldcover(grid: GridSpec, year: int = 2020) -> NDArray[np.uint8]:
    min_lon, min_lat, max_lon, max_lat = grid.lonlat_bounds()
    tiles = {_worldcover_tile(x, y) for x in (min_lon, max_lon) for y in (min_lat, max_lat)}
    if len(tiles) != 1:
        raise NotImplementedError(f"AOI spans several WorldCover tiles: {sorted(tiles)}")
    url = WORLDCOVER_URLS[year].format(tile=tiles.pop())
    return _read_to_grid(url, grid, Resampling.nearest, "uint8")
