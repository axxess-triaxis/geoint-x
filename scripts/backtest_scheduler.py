# ruff: noqa: E501  (markdown report templates are kept on single lines)
"""Backtest the monitoring agent's scheduling against the real acquisition catalogue.

Run from the backend directory:

    uv run python ../scripts/backtest_scheduler.py [--out ../docs/BACKTEST.md]

What this measures (and does not):
* Replays each calendar year 2020-2025 week by week. Each week the agent may
  analyse ONE area, choosing among the Sentinel-2 acquisitions that actually
  occurred over each area in the preceding 7 days (from the demo pack catalogue).
* Usability is proxied by scene-level cloud cover from STAC (AOI-level SCL is
  not available offline for every acquisition). A choice is "usable" if the
  scene had <= 20% cloud.
* Metrics: usable analyses per year, mean and worst staleness (days since each
  area's last usable analysis, sampled weekly), and district coverage evenness
  (Jain index of usable analyses).
* There is no change-detection ground truth in this replay, so the change
  likelihood term is held neutral for every strategy. This evaluates the
  logistics of "where to look next", not detection accuracy.
Each year is a paired comparison (same weather, same acquisitions).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geointx.agent.preview import AreaMemory, Candidate, jain_index, preview
from geointx.imagery.pack import DemoPack, parse_dt
from geointx.models import SceneRef
from geointx.services import district_of

STRATEGIES = ("round_robin", "clearest_scene", "marginal_value", "marginal_value_cost_aware")
USABLE_CLOUD = 20.0


@dataclass
class Area:
    id: str
    name: str
    district: str
    megapixels: float
    acquisitions: list[tuple[datetime, float, str]]  # (when, cloud %, scene id)


def load_areas(pack: DemoPack) -> list[Area]:
    out = []
    for aoi_id in pack.aoi_ids:
        meta = pack.aoi(aoi_id)
        b = meta["bbox"]
        acq = sorted(
            (parse_dt(r["datetime"]), float(r.get("cloud_cover") or 100.0), r["scene_id"])
            for r in pack.catalog(aoi_id)
            if r.get("contains_aoi")
        )
        g = meta["grid"]
        out.append(
            Area(
                id=aoi_id,
                name=meta["name"],
                district=district_of(pack, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2) or aoi_id,
                megapixels=g["width"] * g["height"] / 1e6,
                acquisitions=acq,
            )
        )
    return out


def outlook(area: Area, now: datetime) -> float:
    """Historical share of clear acquisitions in the next 60 days, prior years only."""
    doy = now.timetuple().tm_yday
    hits = total = 0
    for when, cloud, _ in area.acquisitions:
        if when.year >= now.year:
            continue
        if (when.timetuple().tm_yday - doy) % 366 <= 60:
            total += 1
            hits += cloud <= USABLE_CLOUD
    return hits / total if total else 0.5


def simulate(areas: list[Area], year: int, strategy: str) -> dict[str, float]:
    start = datetime(year, 1, 1, tzinfo=UTC)
    last_usable: dict[str, datetime] = {a.id: start - timedelta(days=30) for a in areas}
    last_any: dict[str, datetime] = dict(last_usable)
    usable_by_district: dict[str, float] = {a.district: 0.0 for a in areas}
    usable = attempts = 0
    staleness_samples: list[float] = []
    worst = 0.0
    mean_mp = sum(a.megapixels for a in areas) / len(areas)
    now = start
    while now.year == year:
        week_ago = now - timedelta(days=7)
        options: list[tuple[Area, datetime, float, str]] = []
        for a in areas:
            recent = [x for x in a.acquisitions if week_ago < x[0] <= now]
            if recent:
                when, cloud, sid = recent[-1]  # most recent acquisition this week
                options.append((a, when, cloud, sid))
        choice = None
        if options:
            if strategy == "round_robin":
                choice = min(options, key=lambda o: (last_any[o[0].id], o[0].id))
            elif strategy == "clearest_scene":
                choice = min(options, key=lambda o: (o[2], o[0].id))
            else:
                previews = []
                for a, when, cloud, sid in options:
                    cand = Candidate(
                        aoi_id=a.id,
                        aoi_name=a.name,
                        mode="lulc",
                        district=a.district,
                        prev_scene=SceneRef(
                            scene_id="prev", collection="c", datetime=last_any[a.id]
                        ),
                        next_scene=SceneRef(
                            scene_id=sid, collection="c", datetime=when, cloud_cover=cloud
                        ),
                        cursor=last_usable[a.id],
                        megapixels=a.megapixels,
                    )
                    p = preview(
                        cand,
                        AreaMemory(),
                        now,
                        outlook(a, now),
                        usable_by_district,
                        mean_mp,
                        cost_aware=strategy == "marginal_value_cost_aware",
                    )
                    previews.append((p.score, a.id, (a, when, cloud, sid)))
                choice = max(previews)[2]
        if choice is not None:
            a, when, cloud, _ = choice
            attempts += 1
            last_any[a.id] = when
            if cloud <= USABLE_CLOUD:
                usable += 1
                last_usable[a.id] = when
                usable_by_district[a.district] += 1
        for a in areas:
            d = (now - last_usable[a.id]).days
            staleness_samples.append(d)
            worst = max(worst, d)
        now += timedelta(days=7)
    return {
        "usable_analyses": usable,
        "attempts": attempts,
        "usable_share": usable / attempts if attempts else 0.0,
        "mean_staleness_days": statistics.fmean(staleness_samples),
        "worst_staleness_days": worst,
        "coverage_evenness": jain_index(list(usable_by_district.values())),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--pack", default=str(root / "data" / "demo_pack"))
    ap.add_argument("--out", default=str(root / "docs" / "BACKTEST.md"))
    args = ap.parse_args()
    areas = load_areas(DemoPack(Path(args.pack)))
    years = list(range(2020, 2026))
    results = {s: {y: simulate(areas, y, s) for y in years} for s in STRATEGIES}

    metrics = (
        "usable_analyses",
        "usable_share",
        "mean_staleness_days",
        "worst_staleness_days",
        "coverage_evenness",
    )
    lines = [
        "# Scheduler backtest (real Sentinel-2 acquisition catalogue)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/backtest_scheduler.py`. "
        f"{len(areas)} areas: "
        + ", ".join(f"{a.name} ({len(a.acquisitions)} acquisitions)" for a in areas)
        + ".",
        "",
        "One analysis per week, chosen among acquisitions that actually occurred over each area in the "
        "preceding 7 days. Usable = scene cloud <= 20%. Change likelihood held neutral (no ground truth). "
        "Each year is a paired comparison.",
        "",
        "## Per-year results",
        "",
        "| Year | Strategy | Usable analyses | Usable share | Mean staleness (d) | Worst staleness (d) | Coverage evenness |",
        "|---|---|---|---|---|---|---|",
    ]
    for y in years:
        for s in STRATEGIES:
            r = results[s][y]
            lines.append(
                f"| {y} | {s} | {r['usable_analyses']:.0f} | {r['usable_share']:.2f} | "
                f"{r['mean_staleness_days']:.1f} | {r['worst_staleness_days']:.0f} | {r['coverage_evenness']:.3f} |"
            )
    lines += ["", "## Paired differences vs round robin (mean over years, with per-year range)", ""]
    lines += [
        "| Strategy | Metric | Mean delta | Min | Max | Years better |",
        "|---|---|---|---|---|---|",
    ]
    better_high = {"usable_analyses", "usable_share", "coverage_evenness"}
    for s in STRATEGIES[1:]:
        for m in metrics:
            deltas = [results[s][y][m] - results["round_robin"][y][m] for y in years]
            wins = sum((d > 0) if m in better_high else (d < 0) for d in deltas)
            lines.append(
                f"| {s} | {m} | {statistics.fmean(deltas):+.2f} | {min(deltas):+.2f} | {max(deltas):+.2f} | {wins}/{len(years)} |"
            )
    lines += [
        "",
        "## Reading this honestly",
        "",
        "- This replay evaluates observation logistics only. It cannot show whether the agent finds "
        "more real change, because there is no labelled change ground truth for these areas.",
        "- Scene-level cloud cover is a proxy; the live agent uses the measured AOI clear fraction (SCL).",
        "- Results are reported as produced, including metrics where the baseline is better.",
        "- History: the first version of the agent divided value by processing cost (area in "
        "megapixels). This backtest showed it starved the largest area (worse coverage evenness "
        "than round robin in every year), so cost-awareness is now off by default. The "
        "cost-aware variant is kept in this table for comparison.",
    ]
    Path(args.out).write_text("\n".join(lines) + "\n", "utf-8")
    (Path(args.out).with_suffix(".json")).write_text(json.dumps(results, indent=1), "utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
