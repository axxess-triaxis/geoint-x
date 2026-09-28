from __future__ import annotations

import pytest

from geointx.cases.audit import GENESIS, event_hash, verify_chain
from geointx.cases.workflow import WorkflowError, allowed_actions, transition


def test_happy_path_confirm() -> None:
    s = transition("UNVERIFIED", "start_review", "reviewer")
    assert s == "UNDER_REVIEW"
    assert transition(s, "confirm", "reviewer", note="Construction visible on site") == "CONFIRMED"


@pytest.mark.parametrize(
    ("status", "action", "role", "note", "reason", "msg"),
    [
        ("UNVERIFIED", "confirm", "reviewer", "x", None, "cannot 'confirm'"),
        ("UNVERIFIED", "start_review", "analyst", None, None, "role 'analyst'"),
        ("UNDER_REVIEW", "confirm", "reviewer", "  ", None, "requires a note"),
        ("UNDER_REVIEW", "reject", "reviewer", "x", None, "requires a reason"),
        ("CONFIRMED", "reopen", "reviewer", "x", None, "role 'reviewer'"),
        ("REJECTED", "confirm", "supervisor", "x", None, "cannot 'confirm'"),
    ],
)
def test_illegal_transitions(
    status: str, action: str, role: str, note: str | None, reason: str | None, msg: str
) -> None:
    with pytest.raises(WorkflowError, match=msg):
        transition(status, action, role, note, reason)  # type: ignore[arg-type]


def test_reject_and_reopen() -> None:
    s = transition("UNDER_REVIEW", "reject", "reviewer", "Paddy fallow", "seasonal_or_phenology")
    assert s == "REJECTED"
    assert transition(s, "reopen", "supervisor", "New field report") == "UNDER_REVIEW"


def test_allowed_actions_by_role() -> None:
    assert "confirm" not in allowed_actions("UNDER_REVIEW", "analyst")
    assert "confirm" in allowed_actions("UNDER_REVIEW", "reviewer")
    assert allowed_actions("CONFIRMED", "reviewer") == ["add_note", "attach"]


def _chain(n: int) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    prev = GENESIS
    for i in range(1, n + 1):
        body = {"seq": i, "case_id": "CASE-0001", "action": "add_note", "payload": {"note": str(i)}}
        h = event_hash(prev, body)
        events.append({**body, "prev_hash": prev, "hash": h})
        prev = h
    return events


def test_audit_chain_verifies() -> None:
    assert verify_chain(_chain(5)).ok  # type: ignore[arg-type]


def test_audit_chain_detects_tampering() -> None:
    events = _chain(5)
    events[2]["payload"] = {"note": "edited later"}
    check = verify_chain(events)  # type: ignore[arg-type]
    assert not check.ok and check.first_bad_seq == 3 and check.reason == "content hash mismatch"


def test_audit_chain_detects_deletion() -> None:
    events = _chain(5)
    del events[1]
    check = verify_chain(events)  # type: ignore[arg-type]
    assert not check.ok and check.first_bad_seq == 3
