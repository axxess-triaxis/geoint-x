"""Frozen demo pack: real Sentinel-2 scenes captured once, stored with provenance.

The pack exists so a demonstration never depends on live network access. Every
scene in it is a real observation; the manifest records the STAC item id, the
capture date, cloud statistics, file hashes and licences. Nothing is simulated.

Layout::

    <root>/manifest.json
    <root>/assam_districts.geojson
    <root>/<aoi_id>/scenes/<scene_id>.tif   6 bands: blue green red nir swir16 scl (DN)
    <root>/<aoi_id>/worldcover_2020.tif
    <root>/<aoi_id>/polygons.geojson
    <root>/<aoi_id>/catalog.json            all S2 acquisitions over the AOI (metadata only)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from shapely.geometry import shape

from geointx.change.detect import Observation, valid_from_scl
from geointx.geo.grid import GridSpec
from geointx.geo.overlap import MonitoredPolygon
from geointx.imagery.stac import dn_to_reflectance
from geointx.models import SceneRef

PACK_BANDS = ("blue", "green", "red", "nir", "swir16", "scl")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_scene(path: Path, grid: GridSpec, dn: dict[str, NDArray]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    stack = np.stack([dn[b].astype(np.uint16) for b in PACK_BANDS])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=grid.width,
        height=grid.height,
        count=len(PACK_BANDS),
        dtype="uint16",
        crs=grid.crs,
        transform=grid.transform,
        compress="deflate",
        predictor=2,
        zlevel=9,
        tiled=True,
        nodata=0,
    ) as dst:
        dst.write(stack)
        dst.descriptions = PACK_BANDS
    return sha256_file(path)


def write_single(path: Path, grid: GridSpec, arr: NDArray[np.uint8]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=grid.width,
        height=grid.height,
        count=1,
        dtype="uint8",
        crs=grid.crs,
        transform=grid.transform,
        compress="deflate",
        zlevel=9,
        tiled=True,
    ) as dst:
        dst.write(arr, 1)
    return sha256_file(path)


class DemoPack:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest: dict[str, Any] = json.loads((root / "manifest.json").read_text("utf-8"))

    @property
    def aoi_ids(self) -> list[str]:
        return list(self.manifest["aois"].keys())

    def aoi(self, aoi_id: str) -> dict[str, Any]:
        return self.manifest["aois"][aoi_id]  # type: ignore[no-any-return]

    def grid(self, aoi_id: str) -> GridSpec:
        return GridSpec.from_dict(self.aoi(aoi_id)["grid"])

    def scenes(self, aoi_id: str) -> list[SceneRef]:
        return [SceneRef.model_validate(s["scene"]) for s in self.aoi(aoi_id)["scenes"]]

    def load_observation(self, aoi_id: str, scene_id: str) -> Observation:
        entry = next(s for s in self.aoi(aoi_id)["scenes"] if s["scene"]["scene_id"] == scene_id)
        grid = self.grid(aoi_id)
        with rasterio.open(self.root / entry["file"]) as src:
            data = src.read()
        dn = dict(zip(PACK_BANDS, data, strict=True))
        valid = valid_from_scl(dn["scl"]) & (dn["red"] > 0)
        bands = {b: dn_to_reflectance(dn[b]) for b in PACK_BANDS if b != "scl"}
        return Observation(
            scene=SceneRef.model_validate(entry["scene"]), grid=grid, bands=bands, valid=valid
        )

    def load_baseline(self, aoi_id: str) -> NDArray[np.uint8] | None:
        rel = self.aoi(aoi_id).get("worldcover", {}).get("2020")
        if not rel:
            return None
        with rasterio.open(self.root / rel["file"]) as src:
            return src.read(1).astype(np.uint8)

    def load_polygons(self, aoi_id: str) -> list[MonitoredPolygon]:
        rel = self.aoi(aoi_id).get("polygons")
        if not rel:
            return []
        fc = json.loads((self.root / rel).read_text("utf-8"))
        return [
            MonitoredPolygon(
                id=f["properties"]["id"],
                name=f["properties"]["name"],
                kind=f["properties"]["kind"],
                geometry_wgs84=shape(f["geometry"]),
                source=f["properties"]["source"],
                official=bool(f["properties"].get("official", False)),
                buffer_m=float(f["properties"].get("buffer_m", 200.0)),
            )
            for f in fc["features"]
        ]

    def polygons_geojson(self, aoi_id: str) -> dict[str, Any]:
        rel = self.aoi(aoi_id).get("polygons")
        if not rel:
            return {"type": "FeatureCollection", "features": []}
        return json.loads((self.root / rel).read_text("utf-8"))  # type: ignore[no-any-return]

    def catalog(self, aoi_id: str) -> list[dict[str, Any]]:
        rel = self.aoi(aoi_id).get("catalog")
        if not rel:
            return []
        return json.loads((self.root / rel).read_text("utf-8"))  # type: ignore[no-any-return]

    def districts_geojson(self) -> dict[str, Any]:
        rel = self.manifest.get("districts")
        if not rel:
            return {"type": "FeatureCollection", "features": []}
        return json.loads((self.root / rel["file"]).read_text("utf-8"))  # type: ignore[no-any-return]


@lru_cache(maxsize=4)
def open_pack(root: str) -> DemoPack:
    return DemoPack(Path(root))


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
