"""Checks generated listing copy against Santerra's approved-claims policy
before it can ship. Deterministic, not an LLM call — per the architecture's
own guidance, a policy/compliance gate should be a rule engine the model
can't talk its way around, not another model call auditing itself.

The phrase lists below are sourced from
knowledge_base/sustainability_and_claims.md ("Environmental Claims Policy");
tests/test_fact_validator.py asserts they still appear there, so an edit to
that document that removes a phrase gets caught rather than silently
drifting out of sync.
"""

from __future__ import annotations

from agents.models import FactValidationResult, GeneratedListing

# "Claims Requiring Verification" — Santerra has not substantiated these and
# they must not appear in generated copy without separate proof on file.
BLOCKED_UNVERIFIED_CLAIMS = [
    "fully biodegradable",
    "compostable",
    "carbon neutral",
    "zero waste",
    "plastic-free",
    "100% sustainable",
]

# "Approved Claims" / "Approved Messaging" — safe to use as written.
APPROVED_CLAIM_PHRASES = [
    "designed with sustainability in mind",
    "moving toward biodegradable solutions",
    "responsible material choices",
    "responsibly sourced paper",
    "fsc-aligned sourcing approach",
]


def _listing_text(generated: GeneratedListing) -> str:
    parts = [generated.title, generated.description, *generated.highlights, *generated.keywords]
    return " ".join(parts).lower()


def validate_claims(generated: GeneratedListing) -> FactValidationResult:
    text = _listing_text(generated)

    blocked = [claim for claim in BLOCKED_UNVERIFIED_CLAIMS if claim in text]
    verified = [claim for claim in APPROVED_CLAIM_PHRASES if claim in text]

    return FactValidationResult(
        verified_claims=verified,
        blocked_claims=blocked,
        passed=len(blocked) == 0,
    )
