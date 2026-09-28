# Demo pack

What is tracked in git:
- `demo_pack/manifest.json`: provenance and hashes.
- `demo_pack/*/catalog.json`: full Sentinel-2 acquisition metadata per area.
- `demo_pack/*/polygons.geojson`: OSM boundaries.
- `demo_pack/assam_districts.geojson`.

The rasters (21 Sentinel-2 scene stacks plus 3 WorldCover tiles, about 190 MB) are published as a
GitHub release asset, `demo_pack.tar.gz`, to keep the repository small.

```bash
cd backend && uv run python ../scripts/demo_pack_archive.py fetch
```

This downloads the archive, extracts it, and verifies every raster against `manifest.json`. To
rebuild everything from the live public sources instead:

```bash
cd backend && uv run python ../scripts/build_demo_pack.py
```
