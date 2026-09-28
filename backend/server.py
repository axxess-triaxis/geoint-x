"""Vercel (serverless) entrypoint: exposes the FastAPI instance as ``app``.

On Vercel the build step (``vercel_build.py``) places the dashboard build and the
demo-pack metadata in ``_bundle/``. At runtime only ``/tmp`` is writable, so the
pack metadata is copied there and the ~200 MB of rasters are streamed from the
GitHub release on first use and hash-verified (they exceed the bundle budget).

Limitation: state (SQLite database, generated evidence) lives in ``/tmp`` of the
running instance. It survives while the instance stays warm and is lost when the
platform recycles it. A persistent database is needed for anything beyond a demo.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

from geointx.api.app import create_app  # noqa: E402
from geointx.settings import Settings  # noqa: E402

BUNDLE = HERE / "_bundle"


def _serverless_settings() -> Settings:
    var = Path(os.environ.get("GEOINTX_VAR_DIR", "/tmp/geointx"))
    pack = var / "pack"
    if not (pack / "manifest.json").exists():
        shutil.copytree(BUNDLE / "demo_pack", pack, dirs_exist_ok=True)
    return Settings(
        pack_dir=pack,
        var_dir=var,
        frontend_dist=BUNDLE / "frontend",
        pack_autofetch=True,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GEOINTX_GEMINI_API_KEY"),
    )


app = create_app(_serverless_settings() if BUNDLE.exists() else None)
