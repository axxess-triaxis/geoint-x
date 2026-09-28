"""Vercel (serverless) entrypoint: exposes the FastAPI instance as ``app``.

On Vercel the build step (``vercel_build.py``) places the dashboard build and the
demo-pack metadata in ``_bundle/``. At runtime only ``/tmp`` is writable, so the
pack metadata is copied there and the ~200 MB of rasters are streamed from the
GitHub release on first use and hash-verified (they exceed the bundle budget).

If initialisation fails, the app still boots and every request returns HTTP 503
with the error type and message, so a failed deployment explains itself instead
of returning an opaque platform error.

Limitation: state (SQLite database, generated evidence) lives in ``/tmp`` of the
running instance. It survives while the instance stays warm and is lost when the
platform recycles it. A persistent database is needed for anything beyond a demo.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

log = logging.getLogger("geointx.server")
BUNDLE = HERE / "_bundle"
ON_VERCEL = bool(os.environ.get("VERCEL"))


def _settings():  # type: ignore[no-untyped-def]
    from geointx.settings import Settings

    if not (BUNDLE.exists() or ON_VERCEL):
        return None  # plain local run: normal defaults
    var = Path(os.environ.get("GEOINTX_VAR_DIR", "/tmp/geointx"))
    pack = var / "pack"
    if not (pack / "manifest.json").exists():
        src = BUNDLE / "demo_pack"
        if not (src / "manifest.json").exists():
            raise RuntimeError(
                f"demo-pack metadata not found at {src}: the build step "
                "(python vercel_build.py) did not run. Set the project's Root Directory to "
                "'backend' so [tool.vercel.scripts] build is used."
            )
        shutil.copytree(src, pack, dirs_exist_ok=True)
    return Settings(
        pack_dir=pack,
        var_dir=var,
        frontend_dist=BUNDLE / "frontend",
        pack_autofetch=True,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GEOINTX_GEMINI_API_KEY"),
    )


def _startup_failed(err: BaseException) -> FastAPI:
    detail = f"{type(err).__name__}: {err}"[:600]
    fallback = FastAPI(title="GEOINT-X (startup failed)")

    @fallback.api_route("/{path:path}", methods=["GET", "POST", "HEAD"], include_in_schema=False)
    def failed(path: str) -> JSONResponse:
        return JSONResponse({"status": "startup_failed", "error": detail}, status_code=503)

    return fallback


try:
    from geointx.api.app import create_app

    app = create_app(_settings())
except Exception as exc:  # report, don't crash the platform function
    log.exception("GEOINT-X failed to start")
    app = _startup_failed(exc)
