"""Analytics aggregation, CSV export and printable investigation reports."""

from __future__ import annotations

import csv
import html
import io
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from geointx.change.classify import ClassifierParams, LandState, classify_state
from geointx.change.indices import compute_indices
from geointx.geo.grid import GridSpec
from geointx.imagery.pack import DemoPack
from geointx.models import Finding
from geointx.store.db import AoiRow, CaseEventRow, CaseRow, FindingRow, RunRow


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@lru_cache(maxsize=16)
def land_composition(pack_root: str, aoi_id: str) -> list[dict[str, Any]]:
    """Per-scene land-state shares for an AOI (spectral classes, heuristic)."""
    pack = DemoPack(Path(pack_root))
    out = []
    params = ClassifierParams()
    for sc in sorted(pack.scenes(aoi_id), key=lambda s: s.datetime):
        obs = pack.load_observation(aoi_id, sc.scene_id)
        idx = compute_indices(obs.bands)
        st = classify_state(idx["ndvi"], idx["mndwi"], obs.valid, params)
        valid = st != LandState.NODATA
        n = max(int(valid.sum()), 1)
        px_ha = obs.grid.pixel_area_m2 / 10_000
        out.append(
            {
                "scene_id": sc.scene_id,
                "date": f"{sc.datetime:%Y-%m-%d}",
                "clear_fraction": round(float(valid.mean()), 4),
                "shares": {
                    "water": round(float((st == LandState.WATER).sum() / n), 4),
                    "dense_vegetation": round(float((st == LandState.DENSE_VEG).sum() / n), 4),
                    "sparse_vegetation": round(float((st == LandState.SPARSE_VEG).sum() / n), 4),
                    "bare_or_built": round(float((st == LandState.NONVEG).sum() / n), 4),
                },
                "area_ha": {
                    "water": round(float((st == LandState.WATER).sum() * px_ha), 1),
                    "bare_or_built": round(float((st == LandState.NONVEG).sum() * px_ha), 1),
                },
            }
        )
    return out


def analytics(ses: Session, pack: DemoPack) -> dict[str, Any]:
    cases = list(ses.exec(select(CaseRow)).all())
    runs = list(ses.exec(select(RunRow)).all())
    aois = list(ses.exec(select(AoiRow)).all())
    status_counts: dict[str, int] = defaultdict(int)
    for c in cases:
        status_counts[c.status] += 1
    confirmed, rejected = status_counts["CONFIRMED"], status_counts["REJECTED"]

    # Detected change (all recorded findings) vs. verification (cases only).
    findings = list(ses.exec(select(FindingRow)).all())
    run_period = {r.id: f"{r.t1_datetime:%Y}-{r.t2_datetime:%Y}" for r in runs}
    by_district: dict[str, dict[str, float]] = defaultdict(lambda: {"regions": 0, "area_ha": 0.0})
    by_transition: dict[str, dict[str, float]] = defaultdict(
        lambda: {"regions": 0, "area_ha": 0.0, "cases": 0, "confirmed": 0, "rejected": 0}
    )
    by_period: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    triage_counts: dict[str, int] = defaultdict(int)
    for fr in findings:
        d = by_district[fr.district or "Unknown"]
        d["regions"] += 1
        d["area_ha"] = round(d["area_ha"] + fr.area_ha, 3)
        t = by_transition[fr.transition]
        t["regions"] += 1
        t["area_ha"] = round(t["area_ha"] + fr.area_ha, 3)
        p = by_period[run_period.get(fr.run_id, "unknown")]
        p[fr.transition] = round(p[fr.transition] + fr.area_ha, 3)
        triage_counts[fr.triage or "queued"] += 1
    reject_reasons: dict[str, int] = defaultdict(int)
    for c in cases:
        t = by_transition[c.transition]
        t["cases"] += 1
        if c.status == "CONFIRMED":
            t["confirmed"] += 1
        if c.status == "REJECTED":
            t["rejected"] += 1
            reject_reasons[c.reject_reason or "unspecified"] += 1

    now = datetime.now(UTC)
    coverage = []
    for a in aois:
        grid = GridSpec.from_dict(a.grid)
        cat = (
            [r for r in pack.catalog(a.id) if r.get("contains_aoi")] if a.id in pack.aoi_ids else []
        )
        coverage.append(
            {
                "aoi_id": a.id,
                "name": a.name,
                "mode": a.mode,
                "district": a.district,
                "area_km2": round(grid.width * grid.height * grid.pixel_area_m2 / 1e6, 1),
                "analyses": sum(1 for r in runs if r.aoi_id == a.id),
                "last_observed": None
                if a.last_observed_at is None
                else f"{a.last_observed_at:%Y-%m-%d}",
                "days_since_observation": None
                if a.last_observed_at is None
                else (now - _aware(a.last_observed_at)).days,
                "catalog_acquisitions": len(cat),
                "catalog_clear_share": round(
                    sum(1 for r in cat if (r.get("cloud_cover") or 100) <= 20) / len(cat), 3
                )
                if cat
                else None,
                "monitoring_active": a.monitoring_active,
            }
        )

    composition = {
        a.id: land_composition(str(pack.root), a.id) for a in aois if a.id in pack.aoi_ids
    }
    return {
        "totals": {
            "monitored_areas": len(aois),
            "analyses": len(runs),
            "cases": len(cases),
            "open": status_counts["UNVERIFIED"] + status_counts["UNDER_REVIEW"],
            "p1_open": sum(
                c.priority_band == "P1" and c.status in ("UNVERIFIED", "UNDER_REVIEW")
                for c in cases
            ),
            "confirmed": confirmed,
            "rejected": rejected,
            "rejection_rate": None
            if confirmed + rejected == 0
            else round(rejected / (confirmed + rejected), 3),
            "case_area_ha": round(sum(c.area_ha for c in cases), 2),
            "regions": len(findings),
            "changed_area_ha": round(sum(fr.area_ha for fr in findings), 2),
        },
        "status_counts": dict(status_counts),
        "triage": dict(triage_counts),
        "by_district": dict(by_district),
        "by_transition": dict(by_transition),
        "by_period": {k: dict(v) for k, v in by_period.items()},
        "reject_reasons": dict(reject_reasons),
        "coverage": coverage,
        "land_composition": composition,
        "notes": [
            "Land composition uses heuristic spectral classes (rule-v1.0); 'bare or built' "
            "cannot separate bare soil from built-up surfaces.",
            "Rejection rate counts only cases a reviewer has decided.",
            "Detected-change areas are summed over all analyses; overlapping analysis periods "
            "can count the same ground more than once.",
        ],
    }


CSV_FIELDS = [
    "case_id",
    "status",
    "priority_band",
    "priority_score",
    "aoi_id",
    "district",
    "transition",
    "area_ha",
    "confidence",
    "centroid_lon",
    "centroid_lat",
    "observed_t1",
    "observed_t2",
    "scene_t1",
    "scene_t2",
    "inside_monitored_boundary",
    "algorithm_version",
    "reject_reason",
]


def cases_csv(rows: list[tuple[CaseRow, Finding]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    for c, f in rows:
        w.writerow(
            {
                "case_id": c.id,
                "status": c.status,
                "priority_band": c.priority_band,
                "priority_score": c.priority_score,
                "aoi_id": c.aoi_id,
                "district": c.district or "",
                "transition": c.transition,
                "area_ha": c.area_ha,
                "confidence": c.confidence,
                "centroid_lon": f.centroid[0],
                "centroid_lat": f.centroid[1],
                "observed_t1": f"{f.t1.datetime:%Y-%m-%d}",
                "observed_t2": f"{f.t2.datetime:%Y-%m-%d}",
                "scene_t1": f.t1.scene_id,
                "scene_t2": f.t2.scene_id,
                "inside_monitored_boundary": "; ".join(
                    o.polygon_name for o in f.overlaps if o.fraction_of_finding_inside > 0
                ),
                "algorithm_version": f.algorithm_version,
                "reject_reason": c.reject_reason or "",
            }
        )
    return buf.getvalue()


def _e(x: object) -> str:
    return html.escape(str(x))


def case_report_html(
    c: CaseRow, f: Finding, events: list[CaseEventRow], aoi: AoiRow | None, chain_ok: bool
) -> str:
    before = next((e for e in f.evidence if e.kind == "image_before"), None)
    after = next((e for e in f.evidence if e.kind == "image_after"), None)
    mask = next((e for e in f.evidence if e.kind == "change_mask"), None)
    interp = c.interpretation or {}
    pr = c.priority.get("factors", [])
    overlaps = (
        "".join(
            f"<tr><td>{_e(o.polygon_name)}</td><td>{_e(o.polygon_kind)}</td>"
            f"<td>{o.fraction_of_finding_inside:.0%}</td><td>{o.overlap_ha:.2f} ha</td>"
            f"<td>{'yes' if o.crosses_boundary else 'no'}</td><td>{o.distance_to_boundary_m:.0f} m</td></tr>"
            for o in f.overlaps
        )
        or "<tr><td colspan=6>No monitored boundary inside or within buffer.</td></tr>"
    )
    factors = "".join(
        f"<tr><td>{_e(x['name'].replace('_', ' '))}</td><td>{x['value']:.2f}</td>"
        f"<td>{x['weight']:.2f}</td><td>{x['contribution']:.1f}</td><td>{_e(x['explanation'])}</td></tr>"
        for x in pr
    )
    conf = "".join(
        f"<tr><td>{_e(x.name.replace('_', ' '))}</td><td>{x.value:.2f}</td><td>{x.weight:.2f}</td>"
        f"<td>{_e(x.explanation)}</td></tr>"
        for x in f.confidence_factors
    )
    evidence = "".join(
        f"<tr><td><code>{_e(e.id)}</code></td><td>{_e(e.kind)}</td><td>{_e(e.description)}</td>"
        f"<td><code>{_e((e.sha256 or '')[:16])}</code></td></tr>"
        for e in f.evidence
    )
    evs = "".join(
        f"<tr><td>{ev.seq}</td><td>{_e(ev.ts[:19].replace('T', ' '))}</td><td>{_e(ev.actor)} ({_e(ev.role)})</td>"
        f"<td>{_e(ev.action)}</td><td>{_e(ev.from_status or '')} &rarr; {_e(ev.to_status or '')}</td>"
        f"<td>{_e(ev.payload.get('note', ''))}</td><td><code>{ev.hash[:12]}</code></td></tr>"
        for ev in events
    )
    ai_block = (
        f"<p>{_e(interp.get('summary'))}</p>"
        f"<p class=muted>Source: {_e(interp.get('source'))}"
        f"{' (' + _e(interp.get('model')) + ')' if interp.get('model') else ''}. "
        "Generated text interprets the recorded finding; all figures above come from deterministic analysis.</p>"
        if interp
        else "<p class=muted>No AI interpretation generated for this case.</p>"
    )

    def im(e: Any, label: str) -> str:
        return (
            f"<figure><img src='{_e(e.uri)}' alt='{_e(label)}'><figcaption>{_e(label)}</figcaption></figure>"
            if e and e.uri
            else ""
        )

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{_e(c.id)} investigation report</title>
<style>
body{{font:13px/1.45 system-ui,Segoe UI,sans-serif;color:#1d232a;margin:32px auto;max-width:900px;padding:0 16px}}
h1{{font-size:20px;margin:0}} h2{{font-size:14px;margin:22px 0 6px;border-bottom:1px solid #ccd;padding-bottom:3px}}
table{{border-collapse:collapse;width:100%;font-size:12px}} td,th{{border:1px solid #d7dbe0;padding:4px 6px;text-align:left;vertical-align:top}}
th{{background:#f2f4f6}} .muted{{color:#5c6670}} .banner{{background:#fff4d6;border:1px solid #e5c56b;padding:8px 10px;margin:12px 0}}
.figs{{display:flex;gap:10px}} figure{{margin:0;flex:1}} img{{width:100%;image-rendering:pixelated;border:1px solid #ccd}}
figcaption{{font-size:11px;color:#5c6670}} code{{font-size:11px}}
@media print{{body{{margin:0}} .noprint{{display:none}}}}
</style></head><body>
<p class=noprint><button onclick="window.print()">Print / save as PDF</button></p>
<h1>Investigation report: {_e(c.id)}</h1>
<p class=muted>{_e(aoi.name if aoi else c.aoi_id)} &middot; generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC &middot; status <b>{_e(c.status)}</b>
&middot; priority <b>{_e(c.priority_band)} ({c.priority_score:.0f}/100)</b></p>
<div class=banner>This report describes a <b>suspected</b> land-cover change detected from satellite imagery for human verification.
It is not a legal determination of encroachment. Boundaries marked non-official are indicative only.</div>
<h2>Detected change</h2>
<table><tr><th>Classification</th><td>{_e(f.transition_label)} <span class=muted>({_e(f.algorithm_version)}, heuristic)</span></td></tr>
<tr><th>Affected area</th><td>{f.area_ha:.2f} ha ({f.pixel_count} pixels at 10 m)</td></tr>
<tr><th>Location</th><td>{f.centroid[1]:.5f} N, {f.centroid[0]:.5f} E &middot; {_e(f.district or "district n/a")}</td></tr>
<tr><th>Observed between</th><td>{f.t1.datetime:%d %b %Y} ({_e(f.t1.scene_id)}) and {f.t2.datetime:%d %b %Y} ({_e(f.t2.scene_id)})</td></tr>
<tr><th>Confidence</th><td>{f.confidence:.2f} (heuristic evidence score, not a probability)</td></tr>
<tr><th>Index change</th><td>{", ".join(f"d{_e(k.upper())} {v:+.3f}" for k, v in f.index_deltas.items())}</td></tr>
<tr><th>Persistence</th><td>{"n/a (no later observation)" if f.persistence is None else f"{f.persistence:.0%} in later observations"}</td></tr></table>
<h2>Imagery</h2><div class=figs>{im(before, "Before")}{im(after, "After")}{im(mask, "Detected region")}</div>
<h2>Monitored boundaries</h2><table><tr><th>Boundary</th><th>Kind</th><th>Share inside</th><th>Overlap</th><th>Crosses</th><th>Distance</th></tr>{overlaps}</table>
<h2>Why this priority</h2><table><tr><th>Factor</th><th>Value</th><th>Weight</th><th>Points</th><th>Basis</th></tr>{factors}</table>
<h2>Confidence factors</h2><table><tr><th>Factor</th><th>Value</th><th>Weight</th><th>Basis</th></tr>{conf}</table>
<h2>AI interpretation</h2>{ai_block}
<h2>Evidence register</h2><table><tr><th>Id</th><th>Kind</th><th>Description</th><th>SHA-256 (prefix)</th></tr>{evidence}</table>
<h2>Caveats</h2><ul>{"".join(f"<li>{_e(x)}</li>" for x in f.caveats)}</ul>
<h2>Audit trail</h2><p class=muted>Hash chain verification: <b>{"intact" if chain_ok else "BROKEN"}</b></p>
<table><tr><th>#</th><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Status</th><th>Note</th><th>Hash</th></tr>{evs}</table>
<p class=muted>Imagery: Copernicus Sentinel-2 L2A via Element 84 Earth Search. Baseline: ESA WorldCover 2020 (CC BY 4.0). Boundaries: OpenStreetMap contributors (ODbL) unless stated.</p>
</body></html>"""
