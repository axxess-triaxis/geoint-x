from __future__ import annotations

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from geointx.ai.client import LlmUnavailable
from geointx.ai.interpret import LlmInterpretation, interpret, template, validate
from geointx.models import Finding
from geointx.pipeline import AoiContext, run_detection
from geointx.priority.engine import prioritise
from tests.synthetic import T1, T2, observation, surface_map

T = TypeVar("T", bound=BaseModel)


@pytest.fixture(scope="module")
def finding() -> Finding:
    before = surface_map("veg")
    after = before.copy()
    after[50:70, 100:130] = 2
    out = run_detection(
        run_id="R9",
        t1=observation(before, T1, "s1"),
        t2=observation(after, T2, "s2"),
        later=[],
        baseline=None,
        ctx=AoiContext(aoi_id="t"),
    )
    return out.findings[0]


class FakeLlm:
    model = "fake"

    def __init__(self, out: dict[str, Any] | Exception) -> None:
        self.out = out
        self.calls = 0

    def generate_json(self, system: str, prompt: str, schema: type[T], images: Any = None) -> T:
        self.calls += 1
        if isinstance(self.out, Exception):
            raise self.out
        return schema.model_validate(self.out)


def _good(f: Finding) -> dict[str, Any]:
    return {
        "summary": f"About {f.area_ha} ha of vegetation appears to have become bare or built-up.",
        "evidence_refs": [f.evidence[0].id],
        "plausible_explanations": ["Harvest", "Construction"],
        "verification_steps": ["Field visit"],
        "caveats": ["Heuristic classification"],
    }


def test_valid_model_output_is_accepted_and_cached(finding: Finding) -> None:
    store: dict[str, dict[str, Any]] = {}
    llm = FakeLlm(_good(finding))
    pr = prioritise(finding)
    out, meta = interpret(finding, pr, llm, store.get, store.__setitem__)
    assert out.source == "gemini" and meta["cached"] is False
    out2, meta2 = interpret(finding, pr, llm, store.get, store.__setitem__)
    assert meta2["cached"] is True and llm.calls == 1 and out2.summary == out.summary


def test_unknown_evidence_id_is_rejected(finding: Finding) -> None:
    bad = _good(finding) | {"evidence_refs": ["made-up-evidence"]}
    out, meta = interpret(finding, None, FakeLlm(bad))
    assert out.source == "template"
    assert any("unknown evidence" in p for p in meta["problems"])


def test_fabricated_measurement_is_rejected(finding: Finding) -> None:
    bad = _good(finding) | {"summary": "Roughly 42.7 ha were cleared."}
    _, meta = interpret(finding, None, FakeLlm(bad))
    assert any("unsupported figure: 42.7" in p for p in meta["problems"])


def test_accusatory_language_is_rejected(finding: Finding) -> None:
    bad = _good(finding) | {"summary": "This is illegal construction on the wetland."}
    problems = validate(LlmInterpretation.model_validate(bad), finding, None)
    assert any("accusatory" in p for p in problems)


def test_llm_failure_falls_back_to_template(finding: Finding) -> None:
    out, meta = interpret(finding, None, FakeLlm(LlmUnavailable("429 quota")))
    assert out.source == "template" and "429" in meta["reason"]


def test_template_quotes_only_finding_figures(finding: Finding) -> None:
    pr = prioritise(finding)
    t = template(finding, pr)
    raw = LlmInterpretation(**t.model_dump(exclude={"source", "model"}))
    assert validate(raw, finding, pr) == []
