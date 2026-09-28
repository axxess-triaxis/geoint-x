# GEOINT-X (working name)

**Geospatial change intelligence for Assam.** One engine, two government challenge statements of
the North-East SEVA FIRST Innovation Challenge 2026:

| Challenge | How GEOINT-X addresses it |
|---|---|
| **NESFIC-D-21**: AI-based automated land use / land cover change detection and monitoring | Dual-date Sentinel-2 change detection on fixed analysis grids, rule-based transition classes anchored to ESA WorldCover, land-composition time series, and a monitoring agent that decides which area to re-observe next |
| **NESFIC-D-17**: Integrated government land and wetland encroachment monitoring | The same engine, plus monitored boundaries (wetlands, protected areas, imported government-land parcels) with 200 m watch buffers. Boundary overlap drives priority, and evidence-backed cases go to a role-gated verification workflow with a hash-chained audit trail |

> GEOINT-X flags **suspected** change for human verification. It never declares encroachment or
> illegality. Only a reviewer can confirm or reject a case, and a written note is required.

## What it does

```
OBSERVE ─▶ DETECT ─▶ CLASSIFY ─▶ UNDERSTAND ─▶ PRIORITISE ─▶ VERIFY ─▶ MONITOR
Sentinel-2   indices,   rule-v1       GenAI brief     deterministic   reviewer     agent picks
L2A scenes   SCL mask   transitions   (guarded)       score + reasons workflow     next scene
```

- **Deterministic core** (`backend/src/geointx/change`, `geo`, `priority`):
  - Cloud masking with the Sentinel-2 SCL band, then NDVI / MNDWI / NDBI.
  - Rule-based transitions: water loss/gain, tree cover / cropland / vegetation → bare or built,
    wetland vegetation loss, revegetation.
  - Connected regions of at least 0.5 ha, with exact hectares on a UTM grid.
  - A heuristic confidence score with every factor shown.
  - Persistence: whether the change is still there in later observations.
  - Overlap with monitored boundaries.
  - A priority score with a factor-by-factor breakdown.
- **Findings, not accusations.**
  - Every result is a structured `Finding` with scene provenance (STAC ids), before/after crops
    and change masks, all SHA-256 hashed.
  - Every finding is recorded. Only P1/P2, encroachment-relevant findings open a case.
  - Re-detections update the existing case instead of duplicating it.
- **GenAI where it adds value** (`backend/src/geointx/ai`):
  - Gemini writes investigation briefs and answers questions only from a Finding or from the
    result of an allowlisted query tool.
  - Output is rejected, and a deterministic template used instead, if it:
    - cites an evidence id that does not exist,
    - quotes a figure that is not in the source data, or
    - uses accusatory language.
  - The whole product works with no API key.
- **Agentic monitoring** (`backend/src/geointx/agent`), adapted from the GALL-e-LEO decision
  pipeline:
  - **Candidates** are real captured scenes only.
  - **Scoring** is transparent value terms: change likelihood (from reviewer outcomes),
    staleness, clear-sky urgency, district coverage fairness.
  - **LLM choice** is optional and checked against an allowlist of candidates.
  - **Every decision** is logged with its reason.
- **Dashboard** (`frontend/`, React + MapLibre):
  - overview
  - change-detection workspace with a year-by-year imagery timeline
  - encroachment monitoring with boundary import
  - case investigation: before/after swipe, evidence register, priority breakdown, AI brief,
    workflow, audit trail
  - analytics
  - AI assistant
  - monitoring agent
  - printable investigation report
  - CSV and GeoJSON export

## Data

Real, public, no-authentication sources. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

- **Sentinel-2 L2A Collection 1.** Element 84 Earth Search STAC. The clearest mid-January scene of
  each dry season, 2019-20 to 2025-26, for 3 areas: Deepor Beel, Amingaon–Changsari, Majuli.
- **ESA WorldCover 2020.** Baseline land cover.
- **OpenStreetMap.** Wetland and sanctuary outlines. These are not official records and are
  labelled as such.
- **geoBoundaries 2021.** Assam districts.

The demo runs from a **frozen demo pack**: real observations captured once, with provenance and
hashes. It is not real-time imagery. Rasters are distributed as a release asset; see
[data/README.md](data/README.md).

## Quick start

Requires Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 20+.

```bash
cd backend && uv sync && uv run python ../scripts/demo_pack_archive.py fetch
```

```bash
cd frontend && npm ci && npm run build
```

```bash
cd backend && uv run python -c "from geointx.api.app import main; main()"
```

Then open http://localhost:8000. Set `GEMINI_API_KEY` in `.env` to enable Gemini; without it,
template text is used and labelled as such.

To rebuild the demo pack from live sources (about 15 minutes):
`uv run python ../scripts/build_demo_pack.py`.

## Live deployment

https://geoint-x.vercel.app. It runs as a Vercel Python function with Root Directory `backend`,
region `syd1`, and Large Functions on.
- **Entrypoint:** `backend/server.py`.
- **Build step:** `backend/vercel_build.py` does three things:
  - bundles the hash-verified demo pack;
  - builds the dashboard;
  - vendors the system libraries the GDAL wheel expects.
- **State:** stored in the attached Postgres (Supabase) through `POSTGRES_URL`.
- **Evidence images:** not stored. They are regenerated from the source imagery and served only
  if they match the SHA-256 recorded at detection time.

## Demo script (about 5 minutes)

1. **Change detection** → *Deepor Beel*. Step through the 2020–2026 imagery timeline, then
   **Detect change** (Jan 2020 → Jan 2025).
2. The map shows the detected regions by class; the side panel shows area by class.
3. Open the top case. Review the before/after swipe, measurements, boundary overlap,
   "Why this priority", and the evidence register.
4. **Generate** the AI brief. Then, as a *reviewer*: **Start review** → note → **Confirm change**.
   The audit chain updates.
5. **Monitoring agent** → **Run monitoring cycle**. The agent picks the next real observation,
   runs it, updates existing cases (re-observed / reversal) and opens only new cases.
6. **Analytics** and the **AI assistant** (e.g. *"Which monitored wetlands have the largest
   detected changes?"*) reflect the new state. **Encroachment** shows the boundary view (D-17).

## Verification

| Check | Command |
|---|---|
| Backend tests | `cd backend && uv run pytest` |
| Lint and format | `uv run ruff check src tests ../scripts` and `uv run ruff format --check src tests` |
| Types | `uv run mypy src`, plus `uv run mypy --strict src/geointx/{change,geo,priority,agent,cases}` |
| Frontend | `cd frontend && npm run typecheck && npm run lint && npm run build` |
| End-to-end (Playwright, real data) | `npm run test:e2e` |
| Scheduler backtest | `cd backend && uv run python ../scripts/backtest_scheduler.py` → [docs/BACKTEST.md](docs/BACKTEST.md) |

## Documentation

- [docs/ARCHITECTURE_AUDIT.md](docs/ARCHITECTURE_AUDIT.md): the audit of CopperNick-Vision and
  GALL-e-LEO, and what was reused, refactored or discarded.
- [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md): authentication, quotas and licences for every
  source.
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md): what this prototype does not do or claim.
- [docs/BACKTEST.md](docs/BACKTEST.md): scheduler evaluation on the real acquisition catalogue.

Licence: MIT © 2026 Triaxis Ventures Private Limited. Data licences are listed in
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
