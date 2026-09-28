"""Evidence images, reproducible from source imagery and checked against their hashes.

Every evidence PNG is a deterministic function of (demo-pack scenes, run, finding
geometry). A detection run writes them and records their SHA-256. Where the file
is not available (a fresh serverless instance, or a cleared cache) the image is
regenerated from the same inputs and served **only if** its SHA-256 matches the
recorded one. Evidence integrity therefore does not depend on keeping files.
"""

from __future__ import annotations

import hashlib
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from rasterio import features
from shapely.geometry import shape

from geointx.change.detect import detect_change
from geointx.geo.grid import GridSpec
from geointx.imagery import render
from geointx.imagery.pack import DemoPack

_lock = threading.Lock()


class EvidenceUnavailable(LookupError):
    pass


class EvidenceMismatch(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _true_color(pack: DemoPack, aoi_id: str, scene_id: str) -> NDArray[np.uint8]:
    obs = pack.load_observation(aoi_id, scene_id)
    return render.true_color(obs.bands, obs.valid)


def finding_mask(geometry: dict[str, Any], grid: GridSpec) -> NDArray[np.bool_]:
    """Rasterise a finding's WGS84 polygon back onto the analysis grid.

    Finding polygons follow pixel edges, so burning pixel centres recovers
    exactly the pixels of the detected region.
    """
    geom_utm = grid.from_wgs84(shape(geometry))
    burned = features.rasterize(
        [(geom_utm, 1)],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    )
    return burned.astype(bool)


def _render(
    pack: DemoPack,
    run: dict[str, Any],
    grid: GridSpec,
    name: str,
    finding: dict[str, Any] | None,
) -> bytes:
    aoi, t1, t2 = run["aoi_id"], run["t1_scene_id"], run["t2_scene_id"]
    if name == "before.png":
        return render.encode_png(_true_color(pack, aoi, t1))
    if name == "after.png":
        return render.encode_png(_true_color(pack, aoi, t2))
    if name == "change_mask.png":
        result = detect_change(
            pack.load_observation(aoi, t1), pack.load_observation(aoi, t2), pack.load_baseline(aoi)
        )
        return render.encode_png(render.transition_rgba(result.transitions))
    if finding is None:
        raise EvidenceUnavailable(name)
    stem = name.removeprefix(f"{finding['id']}_").removesuffix(".png")
    mask = finding_mask(finding["geometry"], grid)
    for _, arr, crop_stem, _ in render.finding_crops(
        _true_color(pack, aoi, t1), _true_color(pack, aoi, t2), mask
    ):
        if crop_stem == stem:
            return render.encode_png(arr, render.CROP_UPSCALE)
    raise EvidenceUnavailable(name)


def expected_sha(run: dict[str, Any], finding: dict[str, Any] | None, name: str) -> str | None:
    items = list(run.get("artifacts", [])) + (finding or {}).get("evidence", [])
    for e in items:
        if (e.get("uri") or "").endswith(f"/{name}"):
            return e.get("sha256")  # type: ignore[no-any-return]
    return None


def get_evidence(
    pack: DemoPack,
    cache_dir: Path,
    run: dict[str, Any],
    grid: GridSpec,
    name: str,
    finding: dict[str, Any] | None,
) -> bytes:
    """Cached bytes if present, else regenerate; always verified against the record."""
    want = expected_sha(run, finding, name)
    if want is None:
        raise EvidenceUnavailable(name)
    path = cache_dir / run["id"] / name
    if path.is_file():
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == want:
            return data
    with _lock:
        data = _render(pack, run, grid, name, finding)
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise EvidenceMismatch(
            f"{run['id']}/{name}: regenerated {got[:12]} != recorded {want[:12]}"
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        pass  # cache is best-effort (e.g. full /tmp)
    return data
