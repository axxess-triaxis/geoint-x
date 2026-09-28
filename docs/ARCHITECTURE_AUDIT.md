# Architecture audit: CopperNick-Vision and GALL-e-LEO

Audited on 2026-09-28, before any GEOINT-X code was written. Both local clones matched GitHub
HEAD at that point:

| Repo | Commit |
|---|---|
| `axxess-triaxis/CopperNick-Vision` | `639124e` |
| `axxess-triaxis/GALL-e-LEO` | `8357cee` |

GEOINT-X re-implements selected patterns. It imports no code from either repository and does not
modify either one.

## CopperNick-Vision

Python, about 1.2k lines, 49 tests. A cyclone-risk and sky-observation hackathon project.

**What exists:**
- Gemini structured-output calls: `agent.py`, `sky/vision_detect.py`.
- An LLM router with an allowlist: `sky/router.py`.
- An in-memory RAG store.
- IBTrACS and Open-Meteo loaders.
- A FastAPI app with no UI.

**What does not exist:**
- Geospatial processing. The Earth Engine module only counts Sentinel-2 scenes
  (`data/earth_engine.py:fetch_recent_imagery_count`), and it is not wired up on Cloud Run.
- Raster, vector, GeoJSON or projection code.
- Deterministic image analysis. The "vision" code sends pixels straight to Gemini.
- Persistence.

| Decision | Items |
|---|---|
| **Reused (as patterns)** | Structured JSON calls validated against a pydantic schema, with a bounded timeout. The allowlist split where the LLM selects and deterministic code executes. The `confidence_caveats` convention. Mock-based LLM tests. The Cloud Run container shape. |
| **Refactored** | One client factory instead of three. 429 retry with backoff. A no-key fallback: CopperNick returned HTTP 500 without a key; GEOINT-X returns deterministic templates. `Literal`-typed schemas instead of free strings. Error handling: CopperNick had no try/except anywhere in `src/`. |
| **Discarded** | IBTrACS, Open-Meteo, camera/ONVIF ingestion, sky prompts, arXiv RAG corpus, cyclone and sky schemas. |
| **Built new** | Every geospatial component: STAC access, fixed UTM analysis grids, indices, change classification, vectorisation, area, overlap. Evidence and provenance model, persistence, case workflow, audit chain, dashboard. |

**Known risk carried over:** the Gemini free tier. CopperNick documented 20 requests per day on
`gemini-3.8-flash`. GEOINT-X caches interpretations by content hash and never requires the LLM.

## GALL-e-LEO (Agent Observer)

Python, about 350 lines written by the founder on top of the organisers' starter kit. No tests.

On its 10-seed sweep, the baseline ("trust the platform ranking") won 7 of 10 seeds. Mean total
was 82,036 for the baseline against about 81,720 for the other strategies.

| Decision | Items |
|---|---|
| **Reused (architecture)** | The decision pipeline: legal candidate generation → transparent per-candidate preview (`CandidatePreview`) → strategy → optional LLM validated against the candidate allowlist (`_validated_model_decision`) → deterministic fallback recording `reason` and `decision_source`. The remaining-chances urgency idea, the Jain evenness fairness term, and the seed-sweep evaluation discipline. |
| **Fixed when porting** | (1) The unified strategy double-counted penalty avoidance that `estimated_total_gain` already contained. GEOINT-X counts each term once, with a regression test in `tests/test_agent.py`. (2) The fairness term used `len(done) or 8` as the region count. GEOINT-X uses all monitored districts from the start, also regression-tested. (3) Memory recorded choices, not outcomes. GEOINT-X learns from reviewer confirm/reject outcomes through a Beta posterior. (4) The sweep compared means with no pairing. The GEOINT-X backtest reports paired per-year deltas. |
| **Discarded** | Astronomy simulators, lunar and airmass terms, submission packaging, the duplicated agent folders. |

## Result

Neither repository supplied geospatial processing, a UI or storage; those are new in GEOINT-X.
What carried over is proven discipline:
- deterministic code first;
- the LLM behind validated schemas and allowlists;
- every decision explainable and logged.

The GALL-e-LEO lesson that "clever strategies need to beat a simple baseline" was applied. The
first GEOINT-X scheduler lost to baselines on coverage, was fixed for a stated reason, and both
results are published in [BACKTEST.md](BACKTEST.md).
