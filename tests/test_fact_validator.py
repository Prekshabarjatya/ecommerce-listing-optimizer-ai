from pathlib import Path

from agents.fact_validator import (
    APPROVED_CLAIM_PHRASES,
    BLOCKED_UNVERIFIED_CLAIMS,
    validate_claims,
)
from agents.models import GeneratedListing

KB_FILE = (
    Path(__file__).resolve().parent.parent
    / "knowledge_base"
    / "sustainability_and_claims.md"
)


def _listing(title="", description="", highlights=None, keywords=None) -> GeneratedListing:
    return GeneratedListing(
        title=title,
        description=description,
        highlights=highlights or [],
        keywords=keywords or [],
    )


def test_claim_lists_have_not_drifted_from_knowledge_base_doc():
    kb_text = KB_FILE.read_text(encoding="utf-8").lower()
    for claim in BLOCKED_UNVERIFIED_CLAIMS:
        assert claim in kb_text, f"{claim!r} no longer appears in {KB_FILE.name}"
    for phrase in APPROVED_CLAIM_PHRASES:
        assert phrase in kb_text, f"{phrase!r} no longer appears in {KB_FILE.name}"


def test_unverified_claim_in_description_is_blocked():
    listing = _listing(description="Our wipes are fully biodegradable and carbon neutral.")

    result = validate_claims(listing)

    assert result.passed is False
    assert "fully biodegradable" in result.blocked_claims
    assert "carbon neutral" in result.blocked_claims


def test_unverified_claim_in_keywords_is_also_caught():
    listing = _listing(title="Wipes", keywords=["compostable wipes", "eco friendly"])

    result = validate_claims(listing)

    assert result.passed is False
    assert "compostable" in result.blocked_claims


def test_approved_claim_passes_and_is_recorded():
    listing = _listing(description="Packaging uses responsibly sourced paper.")

    result = validate_claims(listing)

    assert result.passed is True
    assert "responsibly sourced paper" in result.verified_claims
    assert result.blocked_claims == []


def test_listing_with_no_sustainability_claims_passes_cleanly():
    listing = _listing(title="Santerra Aloe Wipes", description="Gentle wipes for daily use.")

    result = validate_claims(listing)

    assert result.passed is True
    assert result.blocked_claims == []
    assert result.verified_claims == []
