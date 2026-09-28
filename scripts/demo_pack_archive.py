"""Package or restore the demo-pack rasters (distributed as a GitHub release asset).

The pack's manifest, acquisition catalogues and vector files live in git; the
GeoTIFF rasters (~190 MB) do not. This script moves them in and out of a single
archive and verifies every file against the sha256 recorded in manifest.json.

    uv run python ../scripts/demo_pack_archive.py pack      # -> data/demo_pack.tar.gz
    uv run python ../scripts/demo_pack_archive.py fetch     # download + verify + extract
    uv run python ../scripts/demo_pack_archive.py verify    # check rasters on disk
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "data" / "demo_pack"
ARCHIVE = ROOT / "data" / "demo_pack.tar.gz"
RELEASE_URL = (
    "https://github.com/axxess-triaxis/geoint-x/releases/download/"
    "demo-pack-2026-09-28/demo_pack.tar.gz"
)


def expected() -> dict[str, str]:
    m = json.loads((PACK / "manifest.json").read_text("utf-8"))
    out: dict[str, str] = {}
    for a in m["aois"].values():
        for s in a["scenes"]:
            out[s["file"]] = s["sha256"]
        for wc in a.get("worldcover", {}).values():
            out[wc["file"]] = wc["sha256"]
    return out


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify() -> int:
    bad = 0
    for rel, digest in expected().items():
        p = PACK / rel
        if not p.exists():
            print(f"MISSING  {rel}")
            bad += 1
        elif sha(p) != digest:
            print(f"MISMATCH {rel}")
            bad += 1
    print(f"{len(expected()) - bad}/{len(expected())} rasters verified")
    return 1 if bad else 0


def pack() -> int:
    if verify():
        return 1
    with tarfile.open(ARCHIVE, "w:gz") as tar:
        for rel in expected():
            tar.add(PACK / rel, arcname=rel)
    print(f"wrote {ARCHIVE} ({ARCHIVE.stat().st_size / 1e6:.1f} MB)")
    return 0


def fetch(url: str) -> int:
    print(f"downloading {url}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
        r.raise_for_status()
        with ARCHIVE.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    allowed = set(expected())
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.name in allowed and m.isfile()]
        tar.extractall(PACK, members=members, filter="data")
    return verify()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pack", "fetch", "verify"])
    ap.add_argument("--url", default=RELEASE_URL)
    a = ap.parse_args()
    return {"pack": pack, "verify": verify}.get(a.cmd, lambda: fetch(a.url))()


if __name__ == "__main__":
    sys.exit(main())
