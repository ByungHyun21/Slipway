"""Lifecycle state machine.

brief -> generated -> gated -> approved -> exported

Forward-only, with one backward edge: a failed gate run bounces an asset
from `gated` back to `generated` (the generation loop). Asset status is the
furthest milestone any revision has reached.
"""

from __future__ import annotations

STATUSES = ["brief", "generated", "gated", "approved", "exported"]


def rank(status: str) -> int:
    return STATUSES.index(status)


def advance(asset: dict, target: str) -> None:
    """Move status forward to *target* (never backward)."""
    if rank(target) > rank(asset["status"]):
        asset["status"] = target


def bounce(asset: dict) -> None:
    """Failed gates: a `gated` asset falls back into the generation loop."""
    if asset["status"] == "gated":
        asset["status"] = "generated"
