"""Deterministic case prioritisation with a factor-by-factor breakdown.

The breakdown is stored with every case so the dashboard (and the AI assistant)
can answer "why was this prioritised?" from recorded numbers rather than
generated text.
"""

from __future__ import annotations

import math

from geointx.models import Finding, PriorityBand, PriorityFactor, PriorityResult

ENGINE_VERSION = "priority-v1.1"

WEIGHTS = {
    "boundary_context": 0.25,
    "transition_severity": 0.15,
    "affected_area": 0.15,
    "confidence": 0.15,
    "persistence": 0.20,
    "area_history": 0.10,
}

# Transitions that do not remove natural cover (e.g. more water inside a wetland)
# get only half the boundary-context weight: they are change, but not the kind
# that encroachment monitoring is looking for.
LOW_CONCERN_SEVERITY = 0.5

# How concerning each transition is, on its own, for monitoring purposes.
SEVERITY: dict[str, float] = {
    "wetland_vegetation_loss": 0.9,
    "water_loss": 0.85,
    "forest_clearing": 0.85,
    "cropland_to_bare_or_built": 0.6,
    "vegetation_to_bare_or_built": 0.6,
    "water_gain": 0.4,
    "revegetation": 0.1,
}

# Monitored-boundary kinds that warrant the highest attention.
PROTECTED_KINDS = {"wetland", "protected_area", "government_land", "water_body"}

P1_THRESHOLD = 70.0
P2_THRESHOLD = 45.0


def _band(score: float) -> PriorityBand:
    if score >= P1_THRESHOLD:
        return "P1"
    if score >= P2_THRESHOLD:
        return "P2"
    return "P3"


def boundary_context_value(finding: Finding) -> tuple[float, str]:
    best = 0.0
    why = "Not inside or near any monitored boundary."
    for o in finding.overlaps:
        if o.polygon_kind not in PROTECTED_KINDS:
            continue
        if o.fraction_of_finding_inside > 0:
            v = 0.6 + 0.4 * o.fraction_of_finding_inside
            if o.crosses_boundary:
                v = max(v, 0.85)
            text = (
                f"{o.fraction_of_finding_inside:.0%} inside '{o.polygon_name}' "
                f"({o.overlap_ha:.2f} ha)"
                + (", crosses its boundary" if o.crosses_boundary else "")
            )
        elif o.within_buffer:
            v = 0.45
            text = f"Within buffer, {o.distance_to_boundary_m:.0f} m from '{o.polygon_name}'"
        else:
            continue
        if v > best:
            best, why = v, text + "."
    return best, why


def prioritise(finding: Finding, prior_confirmed_rate: float | None = None) -> PriorityResult:
    """Score a finding 0-100.

    ``prior_confirmed_rate`` is the posterior share of previously reviewed cases in
    the same area that reviewers confirmed (None when there is no history).
    """
    ctx, ctx_why = boundary_context_value(finding)
    sev = SEVERITY.get(finding.transition, 0.5)
    if ctx > 0 and sev < LOW_CONCERN_SEVERITY:
        ctx *= 0.5
        ctx_why += " Halved: this change type does not remove natural cover."
    if finding.persistence is None:
        pers, pers_why = 0.5, "No later observation yet (neutral 0.5)."
    else:
        pers = finding.persistence
        pers_why = f"{pers:.0%} of the region was still changed in later observation(s)"
        pers_why += "; likely transient (seasonal or water-level)." if pers < 0.25 else "."
    area_v = min(1.0, math.log10(1 + finding.area_ha) / math.log10(1 + 10.0))
    hist = 0.5 if prior_confirmed_rate is None else prior_confirmed_rate
    hist_why = (
        "No prior reviewed cases in this area (neutral 0.5)."
        if prior_confirmed_rate is None
        else f"{prior_confirmed_rate:.0%} posterior confirmation rate for past cases in this area."
    )
    values = {
        "boundary_context": (ctx, ctx_why),
        "transition_severity": (sev, f"'{finding.transition_label}' severity weight {sev:.2f}."),
        "affected_area": (area_v, f"{finding.area_ha:.2f} ha (log scale, saturates at 10 ha)."),
        "confidence": (finding.confidence, f"Detection confidence {finding.confidence:.2f}."),
        "persistence": (pers, pers_why),
        "area_history": (hist, hist_why),
    }
    factors = [
        PriorityFactor(
            name=name,
            value=round(v, 4),
            weight=WEIGHTS[name],
            contribution=round(100 * v * WEIGHTS[name], 2),
            explanation=why,
        )
        for name, (v, why) in values.items()
    ]
    score = round(sum(f.contribution for f in factors), 1)
    return PriorityResult(
        score=score, band=_band(score), factors=factors, engine_version=ENGINE_VERSION
    )
