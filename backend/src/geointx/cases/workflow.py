"""Case verification workflow (pure state machine, no I/O).

AI and deterministic detection only ever create cases in UNVERIFIED. Only a
human with the reviewer or supervisor role can move a case to CONFIRMED or
REJECTED, and that decision requires a written note.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from geointx.models import CaseStatus, Role

Action = Literal["assign", "start_review", "confirm", "reject", "reopen", "add_note", "attach"]

ROLE_RANK: dict[Role, int] = {"analyst": 1, "reviewer": 2, "supervisor": 3}

REJECT_REASONS = (
    "seasonal_or_phenology",
    "cloud_or_shadow_artifact",
    "authorised_development",
    "outside_jurisdiction",
    "duplicate",
    "other",
)


class WorkflowError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    from_states: tuple[CaseStatus, ...] | None  # None: any state
    to_state: CaseStatus | None  # None: status unchanged
    min_role: Role
    note_required: bool = False


RULES: dict[Action, Rule] = {
    "assign": Rule(("UNVERIFIED", "UNDER_REVIEW"), None, "analyst"),
    "start_review": Rule(("UNVERIFIED",), "UNDER_REVIEW", "reviewer"),
    "confirm": Rule(("UNDER_REVIEW",), "CONFIRMED", "reviewer", note_required=True),
    "reject": Rule(("UNDER_REVIEW",), "REJECTED", "reviewer", note_required=True),
    "reopen": Rule(("CONFIRMED", "REJECTED"), "UNDER_REVIEW", "supervisor", note_required=True),
    "add_note": Rule(None, None, "analyst", note_required=True),
    "attach": Rule(None, None, "analyst"),
}


def transition(
    status: CaseStatus,
    action: Action,
    role: Role,
    note: str | None = None,
    reject_reason: str | None = None,
) -> CaseStatus:
    rule = RULES.get(action)
    if rule is None:
        raise WorkflowError(f"unknown action '{action}'")
    if ROLE_RANK[role] < ROLE_RANK[rule.min_role]:
        raise WorkflowError(f"role '{role}' cannot perform '{action}' (needs {rule.min_role})")
    if rule.from_states is not None and status not in rule.from_states:
        raise WorkflowError(f"cannot '{action}' a case in status {status}")
    if rule.note_required and not (note and note.strip()):
        raise WorkflowError(f"'{action}' requires a note")
    if action == "reject" and reject_reason not in REJECT_REASONS:
        raise WorkflowError(f"reject requires a reason, one of {REJECT_REASONS}")
    return rule.to_state or status


def allowed_actions(status: CaseStatus, role: Role) -> list[Action]:
    out: list[Action] = []
    for action, rule in RULES.items():
        if ROLE_RANK[role] < ROLE_RANK[rule.min_role]:
            continue
        if rule.from_states is not None and status not in rule.from_states:
            continue
        out.append(action)
    return out
