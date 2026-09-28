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


# Always present in the runtime image (glibc and the C/C++ runtimes).
_BASE_LIBS = (
    "linux-vdso",
    "ld-linux",
    "libc.so",
    "libm.so",
    "libdl.so",
    "librt.so",
    "libpthread.so",
    "libresolv.so",
    "libutil.so",
    "libnsl.so",
    "libgcc_s.so",
    "libstdc++.so",
)
_NATIVE_PACKAGES = ("rasterio", "pyproj", "shapely", "scipy", "numpy", "PIL")


def vendor_system_libs() -> None:
    """Copy system libraries that native wheels expect but do not vendor.

    The rasterio wheel's GDAL links against the OS ``libexpat.so.1``; the build
    image has it but the serverless runtime image does not ("ImportError:
    libexpat.so.1: cannot open shared object file"). Every shared object in the
    native packages is inspected with ``ldd``; any dependency resolved outside the
    installed packages and not part of the base C runtime is copied into
    ``_bundle/lib`` and preloaded by ``server.py``.
    """
    import importlib.util

    if not sys.platform.startswith("linux") or shutil.which("ldd") is None:
        print("vercel_build: not a Linux build image with ldd; skipping native lib vendoring")
        return
    roots = []
    for pkg in _NATIVE_PACKAGES:
        spec = importlib.util.find_spec(pkg)
        if spec and spec.origin:
            roots.append(Path(spec.origin).parent)
    site = {r.parent for r in roots}
    dst = BUNDLE / "lib"
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True)
    copied: set[str] = set()
    for base in site:
        for so in base.rglob("*.so*"):
            if not any(
                part.startswith(_NATIVE_PACKAGES) for part in so.relative_to(base).parts[:1]
            ):
                continue
            out = subprocess.run(["ldd", str(so)], capture_output=True, text=True).stdout
            for line in out.splitlines():
                if "=>" not in line:
                    continue
                name, _, rest = line.strip().partition(" => ")
                path = rest.split(" (")[0].strip()
                if not path.startswith("/") or name in copied:
                    continue
                if any(name.startswith(b) for b in _BASE_LIBS):
                    continue
                if any(str(Path(path).resolve()).startswith(str(s)) for s in site):
                    continue  # vendored inside a wheel
                shutil.copy2(Path(path).resolve(), dst / name)
                copied.add(name)
    print(f"vercel_build: vendored system libs: {sorted(copied) or 'none'}")


if __name__ == "__main__":
    BUNDLE.mkdir(exist_ok=True)
    copy_pack_metadata()
    vendor_system_libs()
    build_frontend()
