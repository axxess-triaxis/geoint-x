"""Render observations and change maps to PNG evidence artifacts.

A fixed reflectance stretch (not a per-image percentile stretch) is used so that
before/after images are visually comparable: identical surfaces look identical.
"""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from geointx.change.classify import Transition

REFLECTANCE_MAX = 0.22
GAMMA = 1.4

# Fixed categorical slots, identical to the dashboard legend (frontend/src/theme.ts).
TRANSITION_COLORS: dict[int, tuple[int, int, int]] = {
    Transition.WATER_GAIN: (0x2A, 0x78, 0xD6),  # slot 1 blue
    Transition.WATER_LOSS: (0xEB, 0x68, 0x34),  # slot 2 orange
    Transition.REVEGETATION: (0x1B, 0xAF, 0x7A),  # slot 3 aqua
    Transition.CROPLAND_TO_BARE_OR_BUILT: (0xED, 0xA1, 0x00),  # slot 4 yellow
    Transition.WETLAND_VEGETATION_LOSS: (0xE8, 0x7B, 0xA4),  # slot 5 magenta
    Transition.VEGETATION_TO_BARE_OR_BUILT: (0x4A, 0x3A, 0xA7),  # slot 7 violet
    Transition.FOREST_CLEARING: (0xE3, 0x49, 0x48),  # slot 8 red; green skipped
}

Window = tuple[int, int, int, int]  # row0, row1, col0, col1


def true_color(
    bands: dict[str, NDArray[np.float32]], valid: NDArray[np.bool_] | None = None
) -> NDArray[np.uint8]:
    rgb = np.stack([bands["red"], bands["green"], bands["blue"]], axis=-1)
    rgb = np.nan_to_num(rgb, nan=0.0)
    out = np.clip(rgb / REFLECTANCE_MAX, 0, 1) ** (1 / GAMMA)
    img = (out * 255).astype(np.uint8)
    if valid is not None:
        # Hatch-free grey for cloud / no-data so it is never mistaken for land.
        img[~valid] = (img[~valid] * 0.35 + 120).astype(np.uint8)
    return img


def transition_rgba(transitions: NDArray[np.uint8], alpha: int = 200) -> NDArray[np.uint8]:
    h, w = transitions.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    for code, color in TRANSITION_COLORS.items():
        m = transitions == code
        out[m, :3] = color
        out[m, 3] = alpha
    return out


def region_outline_rgba(mask: NDArray[np.bool_]) -> NDArray[np.uint8]:
    from scipy import ndimage

    edge = mask & ~ndimage.binary_erosion(mask)
    out = np.zeros((*mask.shape, 4), dtype=np.uint8)
    out[mask] = (255, 214, 0, 70)
    out[edge] = (255, 214, 0, 255)
    return out


def crop_window(mask: NDArray[np.bool_], pad: int = 30, min_size: int = 80) -> Window:
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    h, w = mask.shape
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    size = max(r1 - r0, c1 - c0, min_size) + 2 * pad
    rc, cc = (r0 + r1) // 2, (c0 + c1) // 2
    r0 = max(0, rc - size // 2)
    c0 = max(0, cc - size // 2)
    return r0, min(h, r0 + size), c0, min(w, c0 + size)


def overlay(base: NDArray[np.uint8], rgba: NDArray[np.uint8]) -> NDArray[np.uint8]:
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    return (base * (1 - a) + rgba[..., :3] * a).astype(np.uint8)


CROP_UPSCALE = 3


def finding_crops(
    tc1: NDArray[np.uint8], tc2: NDArray[np.uint8], mask: NDArray[np.bool_]
) -> list[tuple[str, NDArray[np.uint8], str, str]]:
    """(evidence kind, image, file stem, description) for one finding's crops.

    Shared by detection and by on-demand regeneration, so both produce
    byte-identical evidence.
    """
    r0, r1, c0, c1 = crop_window(mask)
    outline = region_outline_rgba(mask[r0:r1, c0:c1])
    return [
        ("image_before", tc1[r0:r1, c0:c1], "before", "T1 true colour (crop)"),
        ("image_after", tc2[r0:r1, c0:c1], "after", "T2 true colour (crop)"),
        (
            "change_mask",
            overlay(tc2[r0:r1, c0:c1], outline),
            "mask",
            "Detected region outlined on T2",
        ),
    ]


def encode_png(arr: NDArray[np.uint8], upscale: int = 1) -> bytes:
    img = Image.fromarray(arr)
    if upscale > 1:
        img = img.resize((img.width * upscale, img.height * upscale), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_png(arr: NDArray[np.uint8], path: Path, upscale: int = 1) -> str:
    """Write PNG and return its sha256 (hex)."""
    data = encode_png(arr, upscale)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: a concurrent reader never sees a partially written file.
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(data)
    try:
        os.replace(tmp, path)
    except PermissionError:
        # Windows: the destination is open by a reader. If another writer already
        # produced it, keep theirs (same deterministic content) and drop ours.
        tmp.unlink(missing_ok=True)
        if not path.exists():
            raise
    return hashlib.sha256(data).hexdigest()
