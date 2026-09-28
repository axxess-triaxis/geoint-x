"""GenAI interpretation of a deterministic Finding, with hard output guards.

Guards applied to every model response before it is shown:
1. Every ``evidence_refs`` id must exist in the Finding.
2. Every figure quoted with a unit (ha, hectares, %, m) must match a figure in
   the Finding or its priority breakdown (small rounding tolerance).
3. Accusatory legal language is rejected: the system flags suspected change,
   it does not determine encroachment.
A response failing any guard is discarded and the deterministic template is used.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from geointx.ai.client import LlmClient, LlmUnavailable
from geointx.models import Finding, Interpretation, PriorityResult

PROMPT_VERSION = "interpret-v1"

SYSTEM = """You assist government officials reviewing satellite-detected land-cover change in Assam, India.
You receive a FINDING produced by deterministic image analysis. Treat it as the only source of facts.
Rules:
- Never invent measurements, coordinates, dates, place names, or observations. Quote figures exactly as given.
- The finding is a SUSPECTED change for human verification. Never state or imply that encroachment,
  illegality, or wrongdoing has been established.
- Cite evidence only by the ids listed in evidence_ids.
- Give plausible explanations (including benign ones such as seasonal change, agriculture, or
  authorised works) and concrete field or records checks a reviewer could do.
- Be concise and plain. Summary: 2-4 sentences."""

BANNED = re.compile(
    r"\b(illegal(ly)?|unlawful(ly)?|encroacher|guilty|criminal|confirmed encroachment|"
    r"encroachment (is|has been) (confirmed|established|proven))\b",
    re.IGNORECASE,
)
FIGURE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ha\b|hectares?\b|%|m\b|metres?\b|meters?\b)", re.IGNORECASE
)


class LlmInterpretation(BaseModel):
    summary: str
    evidence_refs: list[str]
    plausible_explanations: list[str]
    verification_steps: list[str]
    caveats: list[str]


def facts(finding: Finding, priority: PriorityResult | None) -> dict[str, Any]:
    return {
        "finding_id": finding.id,
        "transition": finding.transition_label,
        "area_ha": finding.area_ha,
        "centroid_lon_lat": finding.centroid,
        "district": finding.district,
        "observed_before": f"{finding.t1.datetime:%Y-%m-%d} ({finding.t1.scene_id})",
        "observed_after": f"{finding.t2.datetime:%Y-%m-%d} ({finding.t2.scene_id})",
        "index_means_before": finding.index_means_t1,
        "index_means_after": finding.index_means_t2,
        "index_deltas": finding.index_deltas,
        "baseline_landcover_share": finding.baseline_landcover,
        "persistence_in_later_scenes": finding.persistence,
        "confidence": finding.confidence,
        "confidence_factors": [f.model_dump() for f in finding.confidence_factors],
        "boundary_overlaps": [o.model_dump() for o in finding.overlaps],
        "priority": None if priority is None else priority.model_dump(),
        "evidence_ids": [e.id for e in finding.evidence],
        "evidence": [
            {"id": e.id, "kind": e.kind, "description": e.description} for e in finding.evidence
        ],
        "system_caveats": finding.caveats,
    }


def _allowed_figures(finding: Finding, priority: PriorityResult | None) -> list[float]:
    vals: list[float] = [finding.area_ha, finding.confidence * 100, finding.confidence]
    for o in finding.overlaps:
        vals += [
            o.overlap_ha,
            o.fraction_of_finding_inside * 100,
            o.distance_to_boundary_m,
            100 * (1 - o.fraction_of_finding_inside),
        ]
    for f in finding.confidence_factors:
        vals += [f.value * 100]
    for sc in (finding.t1, finding.t2):
        if sc.cloud_cover is not None:
            vals.append(sc.cloud_cover)
        if sc.aoi_valid_fraction is not None:
            vals.append(sc.aoi_valid_fraction * 100)
    if finding.persistence is not None:
        vals.append(finding.persistence * 100)
    vals += [v * 100 for v in finding.baseline_landcover.values()]
    if priority is not None:
        vals += [priority.score] + [f.value * 100 for f in priority.factors]
        vals += [f.weight * 100 for f in priority.factors]
    vals += [
        200.0,
        10.0,
        0.5,
        5.0,
    ]  # system constants: buffer, pixel size, MMU, full-size threshold
    return vals


def _matches(x: float, allowed: list[float]) -> bool:
    return any(abs(x - a) <= max(0.051, abs(a) * 0.02) for a in allowed)


def validate(
    interp: LlmInterpretation, finding: Finding, priority: PriorityResult | None
) -> list[str]:
    problems: list[str] = []
    known = {e.id for e in finding.evidence}
    unknown = [r for r in interp.evidence_refs if r not in known]
    if unknown:
        problems.append(f"unknown evidence ids: {unknown}")
    if not interp.evidence_refs:
        problems.append("no evidence cited")
    text = " ".join(
        [
            interp.summary,
            *interp.plausible_explanations,
            *interp.verification_steps,
            *interp.caveats,
        ]
    )
    if m := BANNED.search(text):
        problems.append(f"accusatory language: '{m.group(0)}'")
    allowed = _allowed_figures(finding, priority)
    for num, unit in FIGURE.findall(text):
        if not _matches(float(num), allowed):
            problems.append(f"unsupported figure: {num} {unit}")
    return problems


def template(finding: Finding, priority: PriorityResult | None) -> Interpretation:
    where = f" in {finding.district} district" if finding.district else ""
    inside = [o for o in finding.overlaps if o.fraction_of_finding_inside > 0]
    near = [o for o in finding.overlaps if o.within_buffer]
    ctx = ""
    if inside:
        o = inside[0]
        ctx = (
            f" {o.fraction_of_finding_inside:.0%} of the area ({o.overlap_ha:.2f} ha) lies inside "
            f"the monitored boundary '{o.polygon_name}'."
        )
    elif near:
        o = near[0]
        ctx = f" It lies {o.distance_to_boundary_m:.0f} m outside '{o.polygon_name}'."
    summary = (
        f"Suspected change '{finding.transition_label}' covering {finding.area_ha:.2f} ha{where}, "
        f"observed between {finding.t1.datetime:%d %b %Y} and {finding.t2.datetime:%d %b %Y}.{ctx} "
        f"Detection confidence is {finding.confidence:.2f} (heuristic score)."
    )
    if priority is not None:
        top = max(priority.factors, key=lambda f: f.contribution)
        summary += f" Priority {priority.band} ({priority.score:.0f}/100), driven mainly by {top.name.replace('_', ' ')}."
    explanations = {
        "water_loss": [
            "Seasonal drawdown or drought lowering the water level",
            "Filling or reclamation of water area",
            "Growth of floating or emergent vegetation over open water",
        ],
        "water_gain": [
            "Flooding or high water level",
            "New excavation or pond",
            "River channel shift",
        ],
        "wetland_vegetation_loss": [
            "Clearing or filling of wetland margins",
            "Seasonal drying or burning of marsh vegetation",
            "Agricultural use of wetland edges",
        ],
        "forest_clearing": [
            "Tree felling or land clearing",
            "Construction site preparation",
            "Fire",
        ],
        "cropland_to_bare_or_built": [
            "Harvest or fallow field",
            "Site preparation or new construction",
            "Brick kiln or earth extraction",
        ],
        "vegetation_to_bare_or_built": [
            "Site preparation or new construction",
            "Seasonal drying or harvest",
            "Earth extraction",
        ],
        "revegetation": ["Crop growth", "Natural regrowth", "Plantation"],
    }[finding.transition]
    steps = [
        "Compare the before/after crops and the later-scene persistence for the outlined region.",
        "Check land records and any permissions or approved works for this location.",
        "Arrange a field visit or recent high-resolution imagery to confirm on the ground.",
    ]
    if inside or near:
        steps.insert(
            1, "Verify the monitored boundary against the official record before any action."
        )
    return Interpretation(
        summary=summary,
        evidence_refs=[e.id for e in finding.evidence][:6],
        plausible_explanations=explanations,
        verification_steps=steps,
        caveats=finding.caveats,
        source="template",
    )


def cache_key(model: str, payload: dict[str, Any]) -> str:
    raw = json.dumps({"v": PROMPT_VERSION, "m": model, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def interpret(
    finding: Finding,
    priority: PriorityResult | None,
    llm: LlmClient | None,
    cache_get: Callable[[str], dict[str, Any] | None] | None = None,
    cache_set: Callable[[str, dict[str, Any]], None] | None = None,
    images: list[tuple[bytes, str]] | None = None,
) -> tuple[Interpretation, dict[str, Any]]:
    """Return (interpretation, meta). Meta says where the text came from and why."""
    if llm is None:
        return template(finding, priority), {"source": "template", "reason": "no LLM configured"}
    payload = facts(finding, priority)
    key = cache_key(llm.model, payload)
    if cache_get and (hit := cache_get(key)):
        return Interpretation.model_validate(hit), {"source": hit.get("source"), "cached": True}
    prompt = "FINDING (JSON):\n" + json.dumps(payload, indent=1, default=str)
    try:
        raw = llm.generate_json(SYSTEM, prompt, LlmInterpretation, images=images)
    except LlmUnavailable as e:
        return template(finding, priority), {"source": "template", "reason": str(e)}
    problems = validate(raw, finding, priority)
    if problems:
        return template(finding, priority), {
            "source": "template",
            "reason": "model output rejected by guards",
            "problems": problems,
        }
    result = Interpretation(**raw.model_dump(), source="gemini", model=llm.model)
    if cache_set:
        cache_set(key, result.model_dump())
    return result, {"source": "gemini", "cached": False}
