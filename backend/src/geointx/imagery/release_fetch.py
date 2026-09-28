"""Fetch the demo-pack rasters from the GitHub release, streaming and verifying.

Used where the rasters cannot ship with the code (a serverless bundle is limited
to 500 MB and the rasters are ~200 MB). The archive is streamed straight into the
pack directory (no temporary copy of the archive), only files listed in the
manifest are extracted, and every file is checked against its manifest SHA-256.
A mismatch deletes the file and raises: unverified imagery is never used.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tarfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from geointx.imagery.pack import DemoPack

log = logging.getLogger(__name__)

DEFAULT_URL = (
    "https://github.com/axxess-triaxis/geoint-x/releases/download/"
    "demo-pack-2026-09-28/demo_pack.tar.gz"
)


class _StreamReader:
    """Minimal file-like ``read()`` over an httpx byte iterator (for tarfile 'r|gz')."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._buf = b""

    def read(self, n: int = -1) -> bytes:
        while n < 0 or len(self._buf) < n:
            try:
                self._buf += next(self._chunks)
            except StopIteration:
                break
        if n < 0:
            out, self._buf = self._buf, b""
        else:
            out, self._buf = self._buf[:n], self._buf[n:]
        return out


def expected_rasters(pack: DemoPack) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in pack.manifest["aois"].values():
        for s in a["scenes"]:
            out[s["file"]] = s["sha256"]
        for wc in a.get("worldcover", {}).values():
            out[wc["file"]] = wc["sha256"]
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_rasters(pack: DemoPack) -> None:
    url = os.environ.get("GEOINTX_PACK_URL", DEFAULT_URL)
    wanted = expected_rasters(pack)
    t0 = time.time()
    log.warning("demo pack rasters missing; streaming %s", url)
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        reader = _StreamReader(r.iter_bytes(1 << 20))
        with tarfile.open(fileobj=reader, mode="r|gz") as tar:  # type: ignore[call-overload]
            for member in tar:
                if member.name not in wanted or not member.isfile():
                    continue
                tar.extract(member, pack.root, filter="data")
    bad = []
    for rel, digest in wanted.items():
        p = pack.root / rel
        if not p.exists() or _sha256(p) != digest:
            bad.append(rel)
            p.unlink(missing_ok=True)
    if bad:
        raise RuntimeError(f"demo pack verification failed for {len(bad)} file(s): {bad[:3]}")
    log.warning("demo pack rasters ready: %d files in %.1fs", len(wanted), time.time() - t0)
