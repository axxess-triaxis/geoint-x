"""Append-only, hash-chained audit events.

Each event's hash covers its content and the previous event's hash, so any later
edit or deletion of an event breaks verification from that point on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

GENESIS = "0" * 64


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def event_hash(prev_hash: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical(body)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    reason: str | None = None


def verify_chain(events: list[dict[str, Any]]) -> ChainCheck:
    """``events``: dicts with seq, prev_hash, hash and the hashed body fields."""
    prev = GENESIS
    for i, ev in enumerate(sorted(events, key=lambda e: e["seq"])):
        if ev["seq"] != i + 1:
            return ChainCheck(False, i, ev["seq"], "sequence gap")
        if ev["prev_hash"] != prev:
            return ChainCheck(False, i, ev["seq"], "prev_hash mismatch")
        body = {k: v for k, v in ev.items() if k not in ("hash", "prev_hash", "id")}
        if event_hash(prev, body) != ev["hash"]:
            return ChainCheck(False, i, ev["seq"], "content hash mismatch")
        prev = ev["hash"]
    return ChainCheck(True, len(events))
