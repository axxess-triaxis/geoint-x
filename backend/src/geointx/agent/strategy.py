"""Decision strategies over legal candidates.

An optional LLM may *choose among* legal candidates; its choice is validated
against the allowlist of candidate keys and replaced by the deterministic choice
if invalid. The LLM can never create an observation, scene or area.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from geointx.agent.preview import Preview
from geointx.ai.client import LlmClient, LlmUnavailable

StrategyName = Literal["marginal_value", "round_robin", "llm_assisted"]
DecisionSource = Literal["deterministic", "llm_validated", "llm_rejected_fallback", "no_candidates"]


@dataclass
class Decision:
    chosen: Preview | None
    reason: str
    decision_source: DecisionSource
    strategy: StrategyName


class LlmChoice(BaseModel):
    candidate_key: str
    rationale: str


LLM_SYSTEM = """You help schedule satellite re-observation of monitored land areas.
Choose exactly one candidate_key from the provided candidates. You cannot propose new areas or scenes.
Prefer high score unless the notes give a clear reason otherwise. Keep the rationale to one sentence."""


def _marginal_value(previews: list[Preview]) -> Decision:
    best = max(previews, key=lambda p: (p.score, p.candidate.key))
    top = max(best.terms.items(), key=lambda kv: kv[1] * 1.0)
    reason = (
        f"Highest value per unit cost ({best.score:.3f}): {best.candidate.aoi_name}, "
        f"scene {best.candidate.next_scene.datetime:%Y-%m-%d} "
        f"(clear {best.p_usable:.0%}); strongest term: {top[0].replace('_', ' ')} {top[1]:.2f}."
    )
    return Decision(best, reason, "deterministic", "marginal_value")


def _round_robin(previews: list[Preview]) -> Decision:
    def age(p: Preview) -> float:
        return float("-inf") if p.candidate.cursor is None else p.candidate.cursor.timestamp()

    best = min(previews, key=lambda p: (age(p), p.candidate.key))
    return Decision(
        best,
        f"Round robin: {best.candidate.aoi_name} has gone longest without analysis.",
        "deterministic",
        "round_robin",
    )


def decide(
    previews: list[Preview], strategy: StrategyName = "marginal_value", llm: LlmClient | None = None
) -> Decision:
    if not previews:
        return Decision(
            None,
            "No monitored area has a new usable observation available. Waiting.",
            "no_candidates",
            strategy,
        )
    if strategy == "round_robin":
        return _round_robin(previews)
    fallback = _marginal_value(previews)
    if strategy != "llm_assisted" or llm is None:
        return fallback
    allow = {p.candidate.key: p for p in previews}
    payload = [p.as_dict() for p in previews]
    try:
        choice = llm.generate_json(LLM_SYSTEM, json.dumps(payload, default=str), LlmChoice)
    except LlmUnavailable as e:
        fallback.reason += f" (LLM unavailable: {str(e)[:80]})"
        fallback.strategy = "llm_assisted"
        return fallback
    if choice.candidate_key not in allow:
        fallback.reason = (
            f"LLM proposed '{choice.candidate_key}', which is not a legal candidate; "
            + fallback.reason
        )
        fallback.decision_source = "llm_rejected_fallback"
        fallback.strategy = "llm_assisted"
        return fallback
    return Decision(allow[choice.candidate_key], choice.rationale, "llm_validated", "llm_assisted")
