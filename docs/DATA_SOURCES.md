# Data sources

Every source was checked for access, quota and licence on 2026-09-28, before integration. All
of them were accessed without credentials from this development machine.

| Source | Used for | Access | Quota / limits | Licence |
|---|---|---|---|---|
| **Sentinel-2 L2A Collection 1**, Element 84 Earth Search STAC (`earth-search.aws.element84.com/v1`, collection `sentinel-2-c1-l2a`) | Surface reflectance: blue, green, red, nir, swir16; SCL cloud mask; acquisition catalogue | Public STAC API plus public COGs on AWS S3 (us-west-2). No auth. | No documented hard quota; requests are windowed COG reads (about 10 s per band per AOI) | Copernicus Sentinel data: free, full and open |
| **ESA WorldCover 10 m 2020 v100** (`esa-worldcover.s3.eu-central-1.amazonaws.com`) | Baseline land-cover class used to subtype transitions and for confidence | Public COG, no auth | None documented | CC BY 4.0 |
| **OpenStreetMap** via Overpass API (`overpass-api.de`) | Deepor Beel wetland outline (relation 9630968) and sanctuary outline (way 677514328) | Public, no auth | Fair-use rate limits; the builder pauses between queries | ODbL. **These are not official government boundaries.** |
| **geoBoundaries** IND ADM2 (release 9469f09, 2021) | Assam district attribution: 33 districts, centroid-in-polygon | Public GitHub raw file | None | ODbL (source: Pathways Data Pvt. Ltd., lgdirectory.gov.in) |
| **OpenStreetMap standard tiles** (`tile.openstreetmap.org`) | Dashboard basemap | Public | OSMF tile usage policy: light use, attribution required. Not suitable for production traffic. | ODbL / CC BY-SA |
| **Google Gemini API** (optional) | Investigation briefs and assistant phrasing | API key (`GEMINI_API_KEY`) | Free tier was 20 requests per day in CopperNick's testing. Responses are cached by content hash. | Google API terms |

## Frozen demo pack

`scripts/build_demo_pack.py` captured the pack on **2026-09-28**. Scene selection:
- For each dry season (Nov–Feb) from 2019-20 to 2025-26, take the scene closest to **15 January**
  that fully contains the area, with scene cloud at or below 20% and area clear fraction at or
  above 97% where available.
- Holding the calendar date constant keeps comparisons seasonally consistent. An earlier version
  picked the lowest-cloud scene per season, which mixed November and February scenes. That
  inflates apparent water change in the wetland.

Every scene's STAC id, capture time, scene cloud %, measured area clear fraction (SCL) and file
SHA-256 are recorded in `data/demo_pack/manifest.json`. `scripts/demo_pack_archive.py verify`
re-checks every raster.

The full acquisition catalogue for each area (metadata only) is in
`data/demo_pack/<area>/catalog.json`:

| Area | Acquisitions since Oct 2019 |
|---|---|
| Deepor Beel | 472 |
| Majuli | 465 |

The monitoring agent's clear-sky outlook and the scheduler backtest use these catalogues.

## Known data caveats

- **District attribution** uses geoBoundaries 2021 geometry. Even at full resolution, that
  dataset places the centre of Deepor Beel in *Kamrup*, although the wetland is usually described
  as lying in Kamrup Metropolitan. Attribution follows the dataset. It is labelled as
  "per geoBoundaries 2021, not an official determination" and is not hand-corrected.
- **Assam district count.** geoBoundaries 2021 has 33 districts for Assam. Later administrative
  changes are not reflected.
- **Baseline map date.** ESA WorldCover 2020 is used as the baseline for all analysis periods.
