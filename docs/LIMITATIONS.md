# Limitations: what this prototype does not do or claim

**Not a legal or official determination.** Cases are *suspected* change for verification. OSM
wetland and sanctuary outlines are not official records. Imported boundaries are marked official
only when the importing user asserts they hold the source document.

**Classification is heuristic (rule-v1.0).**
- Transitions come from spectral-index rules: NDVI, MNDWI, NDBI thresholds and deltas, anchored
  to ESA WorldCover 2020. They have **not been validated against field data** for Assam.
- There is no accuracy figure to report yet. Obtaining one needs labelled reference points.
- Bare soil and built-up surfaces cannot be separated by these indices. Classes are named
  "… to bare/built-up" for that reason.
- The `ChangeClassifier` protocol exists so that a trained model can replace the rules.

**Confidence is not a probability.** It is a weighted evidence-strength score over five named
factors, and every factor is shown.

**Seasonal and hydrological variability.**
- Comparing mid-January scenes reduces, but does not remove, water-level and crop-stage effects.
- Many wetland water-change regions have low persistence. The system down-weights these and logs
  reversals, but they still appear as findings.

**Not real-time.**
- The demo runs on a frozen pack of real Sentinel-2 scenes captured on 2026-09-28.
- The live STAC reader (`imagery/stac.py`) is implemented and was used to build the pack.
- Live ingestion inside the monitoring loop (querying new acquisitions on a schedule) is **not
  wired up** in this version. The agent chooses among already-captured scenes.

**Resolution.** At 10 m pixels with a 0.5 ha minimum mapping unit, small structures such as
individual houses or narrow encroachments along an edge are below detection.

**Scheduler evaluation covers logistics only.** The backtest measures clear-sky yield, staleness
and coverage on the real acquisition catalogue. It cannot measure whether the agent finds *more
real change*, because there is no labelled ground truth.

**Identity is a demo.** The analyst / reviewer / supervisor switcher sets request headers. It is
**not authentication**, and there is no access control beyond role rules on workflow actions.

**IoT / field sensors.** Field evidence (photos, documents) can be attached to a case, where it is
hashed and audited. No sensor integration exists.

**Deployment.**
- The live Vercel deployment keeps state in Postgres. Local runs and the Docker image use SQLite,
  which resets when the container restarts.
- Detection on Vercel takes about 30 s per area (Majuli about 95 s, run as a single request under
  the 300 s function limit). Case and event inserts are not batched yet.
- Record ids (RUN-/CASE-) are assigned by counting rows, so two detections started at the same
  moment could collide.
- OSM standard tiles are not for production traffic.
- The Gemini free tier is rate-limited. Without a key, template text is used and labelled.

**Area arithmetic.** Detected-change areas are summed across analyses. Overlapping analysis
periods can count the same ground more than once. The dashboard states this.
