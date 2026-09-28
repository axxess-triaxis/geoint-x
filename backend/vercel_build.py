"""Vercel build step (``[tool.vercel.scripts] build``), run from ``backend/``.

1. Copies the demo-pack metadata (manifest, catalogues, boundaries, districts)
   from ``../data/demo_pack`` into ``_bundle/demo_pack``. Rasters are excluded:
   they are fetched at runtime from the GitHub release (bundle size budget).
2. Builds the dashboard (``../frontend``) and copies ``dist`` to ``_bundle/frontend``.
Fails loudly if either input is missing, rather than deploying a half-working app.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BUNDLE = HERE / "_bundle"


def copy_pack_metadata() -> None:
    src = REPO / "data" / "demo_pack"
    if not (src / "manifest.json").exists():
        sys.exit(f"vercel_build: {src / 'manifest.json'} not found")
    dst = BUNDLE / "demo_pack"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.tif", "scenes"))
    n = sum(1 for p in dst.rglob("*") if p.is_file())
    print(f"vercel_build: copied {n} pack metadata files")


def build_frontend() -> None:
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("vercel_build: npm not found in the build image; cannot build the dashboard")
    web = REPO / "frontend"
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=web, check=True)
    subprocess.run([npm, "run", "build"], cwd=web, check=True)
    dst = BUNDLE / "frontend"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(web / "dist", dst)
    print(f"vercel_build: dashboard copied to {dst}")


if __name__ == "__main__":
    BUNDLE.mkdir(exist_ok=True)
    copy_pack_metadata()
    build_frontend()
