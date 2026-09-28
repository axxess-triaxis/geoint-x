"""Build the frozen demo pack from live public sources.

Run from the backend directory:

    uv run python ../scripts/build_demo_pack.py [--aoi deepor_beel] [--out ../data/demo_pack]

For each seed AOI this fetches: the full Sentinel-2 acquisition catalogue
(metadata only), the clearest dry-season (Nov-Feb) scene for each season, the
ESA WorldCover 2020 baseline, and OSM boundaries. The Assam district layer comes
from geoBoundaries. Every scene written is a real observation; nothing is
synthesised.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import polygonize, unary_union

from geointx.aois import SEED_AOIS, AoiSeed
from geointx.change.detect import valid_from_scl
from geointx.geo.grid import GridSpec
from geointx.imagery import stac
from geointx.imagery.pack import sha256_file, write_scene, write_single

OVERPASS = "https://overpass-api.de/api/interpreter"
GB_ADM1 = "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/"
GB_ADM2 = "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/"
UA = {"User-Agent": "geoint-x-demo-pack-builder/0.1 (research prototype)"}

MAX_SCENE_CLOUD = 20.0
MIN_CLEAR = 0.85
TARGET_CLEAR = 0.97


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def dry_seasons(today: date) -> list[tuple[str, datetime, datetime, datetime]]:
    out = []
    for y in range(2020, today.year + 1):
        start = datetime(y - 1, 11, 1, tzinfo=UTC)
        end = datetime(y, 2, 28, 23, 59, tzinfo=UTC)
        if end.date() < today:
            out.append((f"{y - 1}-{str(y)[2:]}", start, end, datetime(y, 1, 15, 5, tzinfo=UTC)))
    return out


def pick_scene(
    entries: list[stac.CatalogEntry], grid: GridSpec, target: datetime
) -> tuple[stac.CatalogEntry, float] | None:
    """Clearest usable scene closest to the target date.

    Holding the calendar date roughly constant across years keeps comparisons
    seasonally consistent (wetland water level and crop stage vary within the
    dry season), which matters more than squeezing out the last % of clear sky.
    """
    cands = [e for e in entries if e.contains_aoi and (e.scene.cloud_cover or 0) <= MAX_SCENE_CLOUD]
    cands.sort(key=lambda e: abs((e.scene.datetime - target).total_seconds()))
    best: tuple[stac.CatalogEntry, float] | None = None
    for e in cands[:8]:
        scl = stac.read_scene_dn(e.item, grid, ("scl",))["scl"]
        clear = float(valid_from_scl(scl).mean())
        log(f"    {e.scene.scene_id} scene-cloud={e.scene.cloud_cover:.1f}% aoi-clear={clear:.3f}")
        if best is None or clear > best[1]:
            best = (e, clear)
        if clear >= TARGET_CLEAR:
            best = (e, clear)
            break
    if best and best[1] < MIN_CLEAR:
        log(f"    best clear fraction {best[1]:.2f} below {MIN_CLEAR}; season skipped")
        return None
    return best


def overpass_polygon(osm_type: str, osm_id: int) -> Any:
    q = f"[out:json][timeout:90];{osm_type}({osm_id});out geom;"
    r = httpx.post(OVERPASS, data={"data": q}, headers=UA, timeout=120)
    r.raise_for_status()
    el = r.json()["elements"][0]
    if osm_type == "way":
        coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
        return Polygon(coords)
    outers, inners = [], []
    for m in el["members"]:
        if m["type"] != "way" or "geometry" not in m:
            continue
        line = LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
        (inners if m.get("role") == "inner" else outers).append(line)
    outer = unary_union(list(polygonize(unary_union(outers))))
    if inners:
        outer = outer.difference(unary_union(list(polygonize(unary_union(inners)))))
    return outer


def build_polygons(seed: AoiSeed, grid: GridSpec, out_dir: Path) -> str | None:
    if not seed.osm_boundaries:
        return None
    features = []
    for i, b in enumerate(seed.osm_boundaries):
        geom = overpass_polygon(b.osm_type, b.osm_id)
        if not geom.is_valid:
            geom = geom.buffer(0)
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {
                    "id": f"osm-{b.osm_type}-{b.osm_id}",
                    "name": b.name,
                    "kind": b.kind,
                    "source": f"OpenStreetMap {b.osm_type}/{b.osm_id} (ODbL)",
                    "official": False,
                    "buffer_m": seed.buffer_ring_m or 200.0,
                },
            }
        )
        if i == 0 and seed.buffer_ring_m:
            utm = grid.from_wgs84(geom)
            ring = grid.to_wgs84(utm.buffer(seed.buffer_ring_m).difference(utm))
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(ring),
                    "properties": {
                        "id": f"buffer-{b.osm_id}",
                        "name": f"{seed.buffer_ring_m:.0f} m watch buffer",
                        "kind": "watch_buffer",
                        "source": "Derived: buffer of OSM outline (display only)",
                        "official": False,
                    },
                }
            )
        time.sleep(1)
    rel = f"{seed.id}/polygons.geojson"
    (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    (out_dir / rel).write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), "utf-8"
    )
    return rel


def build_districts(out_dir: Path) -> dict[str, Any]:
    meta1 = httpx.get(GB_ADM1, timeout=60, follow_redirects=True).json()
    meta2 = httpx.get(GB_ADM2, timeout=60, follow_redirects=True).json()
    adm1 = httpx.get(meta1["simplifiedGeometryGeoJSON"], timeout=300, follow_redirects=True).json()
    assam = next(
        shape(f["geometry"]) for f in adm1["features"] if f["properties"]["shapeName"] == "Assam"
    )
    adm2 = httpx.get(meta2["simplifiedGeometryGeoJSON"], timeout=300, follow_redirects=True).json()
    feats = []
    for f in adm2["features"]:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        if g.intersects(assam) and g.intersection(assam).area / g.area > 0.5:
            feats.append(
                {
                    "type": "Feature",
                    "geometry": mapping(g),
                    "properties": {"name": f["properties"]["shapeName"]},
                }
            )
    path = out_dir / "assam_districts.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), "utf-8")
    log(f"districts: {len(feats)} Assam districts written")
    return {
        "file": path.name,
        "sha256": sha256_file(path),
        "source": f"geoBoundaries IND ADM2 ({meta2['boundarySource']}), filtered to Assam",
        "license": meta2["boundaryLicense"],
        "year": meta2["boundaryYearRepresented"],
    }


def build_aoi(seed: AoiSeed, out_dir: Path, client: Any) -> dict[str, Any]:
    grid = GridSpec.from_lonlat_bbox(seed.bbox)
    log(f"{seed.id}: grid {grid.width}x{grid.height} px, EPSG:{grid.epsg}")
    today = datetime.now(UTC).date()
    entries = stac.search_scenes(
        seed.bbox, "2019-10-01T00:00:00Z", f"{today}T23:59:59Z", client=client
    )
    catalog = [
        {
            "scene_id": e.scene.scene_id,
            "datetime": e.scene.datetime.isoformat(),
            "cloud_cover": e.scene.cloud_cover,
            "contains_aoi": e.contains_aoi,
            "platform": e.scene.platform,
        }
        for e in entries
    ]
    (out_dir / seed.id).mkdir(parents=True, exist_ok=True)
    (out_dir / seed.id / "catalog.json").write_text(json.dumps(catalog), "utf-8")
    log(f"{seed.id}: catalogue has {len(catalog)} acquisitions")

    scenes = []
    for label, start, end, target in dry_seasons(today):
        season = [e for e in entries if start <= e.scene.datetime <= end]
        log(f"  season {label}: {len(season)} acquisitions")
        picked = pick_scene(season, grid, target)
        if not picked:
            continue
        entry, clear = picked
        dn = stac.read_scene_dn(entry.item, grid)
        rel = f"{seed.id}/scenes/{entry.scene.scene_id}.tif"
        sha = write_scene(out_dir / rel, grid, dn)
        scene = entry.scene.model_copy(update={"aoi_valid_fraction": round(clear, 4)})
        scenes.append(
            {
                "season": label,
                "scene": json.loads(scene.model_dump_json()),
                "file": rel,
                "sha256": sha,
            }
        )
        log(f"  -> {entry.scene.scene_id} ({(out_dir / rel).stat().st_size / 1e6:.1f} MB)")

    wc = stac.read_worldcover(grid, 2020)
    wc_rel = f"{seed.id}/worldcover_2020.tif"
    wc_sha = write_single(out_dir / wc_rel, grid, wc)
    polygons = build_polygons(seed, grid, out_dir)
    return {
        "name": seed.name,
        "mode": seed.mode,
        "bbox": list(seed.bbox),
        "description": seed.description,
        "grid": grid.to_dict(),
        "scenes": scenes,
        "worldcover": {
            "2020": {
                "file": wc_rel,
                "sha256": wc_sha,
                "source": "ESA WorldCover 10 m 2020 v100",
                "license": "CC BY 4.0",
            }
        },
        "polygons": polygons,
        "catalog": f"{seed.id}/catalog.json",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", default=str(Path(__file__).resolve().parent.parent / "data" / "demo_pack")
    )
    ap.add_argument("--aoi", action="append", help="limit to these AOI ids")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {"aois": {}}
    )
    client = stac.open_client()
    for seed in SEED_AOIS:
        if args.aoi and seed.id not in args.aoi:
            continue
        manifest["aois"][seed.id] = build_aoi(seed, out_dir, client)
        manifest_path.write_text(json.dumps(manifest, indent=2), "utf-8")
    if "districts" not in manifest:
        manifest["districts"] = build_districts(out_dir)
    manifest["built_at"] = datetime.now(UTC).isoformat()
    manifest["sources"] = {
        "sentinel2": f"{stac.EARTH_SEARCH_URL} collection {stac.S2_COLLECTION}",
        "sentinel2_license": "Copernicus Sentinel data, free, full and open",
        "worldcover": "ESA WorldCover 10 m 2020 v100 (CC BY 4.0)",
        "boundaries": "OpenStreetMap contributors (ODbL); not official records",
    }
    manifest["note"] = (
        "Frozen demo pack: real Sentinel-2 observations captured on the date above. "
        "Not real-time. Rebuild with scripts/build_demo_pack.py."
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
