"""Deterministic approval gate. See architecture: Risk/Policy Engine — this
is a plain rule, not a model call, so a blocked claim can't be argued past
by a confident-sounding critic score.
"""

from __future__ import annotations

from agents.models import CriticResult, FactValidationResult

APPROVAL_THRESHOLD = 90

APPROVED = "APPROVED"
NEEDS_REVIEW = "NEEDS_REVIEW"
REJECTED = "REJECTED"


def decide_approval_status(
    fact_result: FactValidationResult, critic: CriticResult
) -> str:
    if not fact_result.passed:
        return REJECTED
    if critic.overall >= APPROVAL_THRESHOLD:
        return APPROVED
    return NEEDS_REVIEW
