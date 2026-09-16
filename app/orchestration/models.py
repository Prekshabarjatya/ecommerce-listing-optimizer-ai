from __future__ import annotations

from pydantic import BaseModel

from agents.models import AuditResult, CriticResult, FactValidationResult, GeneratedListing


class PipelineResult(BaseModel):
    run_id: int
    seller_sku: str
    audit: AuditResult
    generated: GeneratedListing
    fact_result: FactValidationResult
    critic: CriticResult
    approval_status: str
