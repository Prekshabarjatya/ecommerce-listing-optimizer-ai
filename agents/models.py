from __future__ import annotations

from pydantic import BaseModel


class AuditResult(BaseModel):
    score: int
    issues: list[str]
    priority: str  # "LOW" | "MEDIUM" | "HIGH"


class GeneratedListing(BaseModel):
    title: str
    highlights: list[str]
    description: str
    keywords: list[str]


class FactValidationResult(BaseModel):
    verified_claims: list[str]
    blocked_claims: list[str]
    passed: bool


class CriticScores(BaseModel):
    seo: int
    readability: int
    completeness: int
    brand_consistency: int


class CriticResult(BaseModel):
    scores: CriticScores
    overall: int
    notes: list[str]
