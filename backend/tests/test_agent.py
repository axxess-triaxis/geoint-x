from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from geointx.agent.preview import (
    WEIGHTS,
    AreaMemory,
    Candidate,
    clear_sky_outlook,
    fairness_gain,
    jain_index,
    preview,
)
from geointx.agent.strategy import decide
from geointx.models import SceneRef

T = TypeVar("T", bound=BaseModel)
NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _scene(sid: str, days_ago: int, clear: float = 0.99) -> SceneRef:
    return SceneRef(
        scene_id=sid,
        collection="c",
        datetime=NOW - timedelta(days=days_ago),
        aoi_valid_fraction=clear,
    )


def _cand(aoi: str, district: str, cursor_days: int | None, clear: float = 0.99) -> Candidate:
    return Candidate(
        aoi_id=aoi,
        aoi_name=aoi,
        mode="lulc",
        district=district,
        prev_scene=_scene(f"{aoi}-p", 400),
        next_scene=_scene(f"{aoi}-n", 10, clear),
        cursor=None if cursor_days is None else NOW - timedelta(days=cursor_days),
        megapixels=1.0,
    )


def test_value_terms_counted_exactly_once() -> None:
    p = preview(_cand("a", "D1", 90), AreaMemory(3, 1, 0.5), NOW, 0.8, {"D1": 0, "D2": 1}, 1.0)
    assert p.value == pytest.approx(sum(WEIGHTS[k] * v for k, v in p.terms.items()))
    assert set(p.terms) == set(WEIGHTS)
    assert p.score == pytest.approx(p.value * p.p_usable / p.cost)


def test_fairness_uses_all_monitored_districts_from_the_start() -> None:
    # Regression for the GALL-e-LEO `len(done) or 8` bug: with one district observed
    # once and two never observed, observing a new district must improve evenness.
    counts = {"A": 1.0, "B": 0.0, "C": 0.0}
    assert jain_index(list(counts.values())) == pytest.approx(1 / 3)
    assert fairness_gain(counts, "B") > 0
    assert fairness_gain(counts, "A") == 0.0


def test_cloudy_scene_loses_to_clear_scene() -> None:
    mem = AreaMemory()
    counts = {"D1": 0.0, "D2": 0.0}
    clear = preview(_cand("clear", "D1", 90, 0.99), mem, NOW, 0.8, counts, 1.0)
    cloudy = preview(_cand("cloudy", "D2", 90, 0.30), mem, NOW, 0.8, counts, 1.0)
    d = decide([cloudy, clear])
    assert d.chosen is clear and d.decision_source == "deterministic"


def test_confirmed_history_raises_priority() -> None:
    counts = {"D1": 0.0}
    hot = preview(_cand("a", "D1", 90), AreaMemory(6, 1, 1.0), NOW, 0.8, counts, 1.0)
    cold = preview(_cand("a", "D1", 90), AreaMemory(1, 6, 0.0), NOW, 0.8, counts, 1.0)
    assert hot.score > cold.score


def test_no_candidates_waits() -> None:
    d = decide([])
    assert d.chosen is None and d.decision_source == "no_candidates"


class FakeLlm:
    model = "fake"

    def __init__(self, key: str) -> None:
        self.key = key

    def generate_json(self, system: str, prompt: str, schema: type[T], images: Any = None) -> T:
        return schema.model_validate({"candidate_key": self.key, "rationale": "because"})


def test_llm_choice_outside_allowlist_is_rejected() -> None:
    counts = {"D1": 0.0}
    ps = [preview(_cand("a", "D1", 90), AreaMemory(), NOW, 0.8, counts, 1.0)]
    d = decide(ps, "llm_assisted", FakeLlm("invented-area:scene"))
    assert d.decision_source == "llm_rejected_fallback" and d.chosen is ps[0]


def test_llm_valid_choice_is_used() -> None:
    counts = {"D1": 0.0, "D2": 0.0}
    ps = [
        preview(_cand("a", "D1", 90), AreaMemory(), NOW, 0.8, counts, 1.0),
        preview(_cand("b", "D2", 90), AreaMemory(), NOW, 0.8, counts, 1.0),
    ]
    d = decide(ps, "llm_assisted", FakeLlm("b:b-n"))
    assert d.decision_source == "llm_validated" and d.chosen is ps[1]


def test_clear_sky_outlook_uses_same_calendar_window() -> None:
    cat: list[dict[str, object]] = [
        {"datetime": datetime(2024, 10, 10, tzinfo=UTC), "cloud_cover": 5.0},
        {"datetime": datetime(2024, 10, 20, tzinfo=UTC), "cloud_cover": 80.0},
        {"datetime": datetime(2025, 7, 1, tzinfo=UTC), "cloud_cover": 90.0},  # outside window
    ]
    share, n = clear_sky_outlook(cat, NOW, horizon_days=60)
    assert n == 2 and share == pytest.approx(0.5)
