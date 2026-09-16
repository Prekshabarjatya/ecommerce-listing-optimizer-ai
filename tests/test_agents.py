import json
from unittest.mock import MagicMock, patch

from agents.audit_agent import audit_listing
from agents.content_agent import generate_listing
from agents.critic_agent import critique_listing
from agents.llm_client import client as llm_client
from agents.models import AuditResult, GeneratedListing


def _mock_llm_response(payload: dict):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    return response


def test_audit_listing_parses_llm_response():
    payload = {"score": 62, "issues": ["Title too generic"], "priority": "MEDIUM"}
    with patch.object(
        llm_client.chat.completions, "create", return_value=_mock_llm_response(payload)
    ) as mock_create:
        result = audit_listing(
            seller_sku="ABC-1",
            seo_title="Wipes",
            description=None,
            keywords=None,
            category="Wipes",
        )

    assert isinstance(result, AuditResult)
    assert result.score == 62
    assert result.priority == "MEDIUM"
    mock_create.assert_called_once()


def test_generate_listing_includes_brand_context_and_audit_issues_in_prompt():
    payload = {
        "title": "Santerra Aloe Vera Wipes Pack of 2",
        "highlights": ["Gentle on skin", "Travel friendly"],
        "description": "Refreshing wipes for daily use.",
        "keywords": ["wet wipes", "aloe vera"],
    }
    audit = AuditResult(score=50, issues=["Title omits pack size"], priority="HIGH")

    with patch.object(
        llm_client.chat.completions, "create", return_value=_mock_llm_response(payload)
    ) as mock_create:
        result = generate_listing(
            seller_sku="ABC-1",
            current_title="wipes",
            current_description=None,
            current_keywords=None,
            category="Wipes",
            audit=audit,
            brand_context=["## Brand Tagline\n\nHygiene for Everyone"],
        )

    assert isinstance(result, GeneratedListing)
    assert result.title == "Santerra Aloe Vera Wipes Pack of 2"

    sent_messages = mock_create.call_args.kwargs["messages"]
    user_message = sent_messages[1]["content"]
    assert "Title omits pack size" in user_message
    assert "Hygiene for Everyone" in user_message


def test_critique_listing_parses_scores():
    payload = {
        "scores": {"seo": 90, "readability": 88, "completeness": 85, "brand_consistency": 95},
        "overall": 90,
        "notes": ["Strong keyword coverage"],
    }
    generated = GeneratedListing(
        title="Santerra Aloe Vera Wipes",
        highlights=["Gentle on skin"],
        description="Refreshing wipes for daily use.",
        keywords=["wet wipes"],
    )

    with patch.object(llm_client.chat.completions, "create", return_value=_mock_llm_response(payload)):
        result = critique_listing(generated)

    assert result.overall == 90
    assert result.scores.brand_consistency == 95
