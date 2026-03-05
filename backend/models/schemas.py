"""
PolyDev Coach - Data Schemas
All Pydantic models for request/response validation.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class Language(str, Enum):
    python = "python"
    java = "java"
    mulesoft = "mulesoft"


class Severity(str, Enum):
    critical = "CRITICAL"
    warning = "WARNING"
    info = "INFO"


class RiskLevel(str, Enum):
    high = "HIGH"
    medium = "MEDIUM"
    low = "LOW"


# ─── Requests ─────────────────────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    code: str = Field(..., min_length=10, description="Source code to review")
    language: Language
    filename: Optional[str] = Field(None, description="Optional filename for context")

    @validator("code")
    def code_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Code cannot be empty or whitespace only")
        return v


class MuleSoftZipReviewRequest(BaseModel):
    """For uploading a full MuleSoft project as a zip"""
    filename: str


# ─── Analyzer output ──────────────────────────────────────────────────────────

class CodeIssue(BaseModel):
    id: str
    severity: Severity
    type: str
    line_range: str
    description: str
    rule_id: str


class AnalysisResult(BaseModel):
    language: str
    issues: List[CodeIssue]
    issue_count: int
    overall_risk: RiskLevel
    # Extra fields from mulesoft_package_validator (when applicable)
    mulesoft_static: Optional[Dict[str, Any]] = None


# ─── Coach output ─────────────────────────────────────────────────────────────

class CoachInsight(BaseModel):
    issue_id: str
    principle: str
    why_it_matters: str
    production_risk: str
    reference: str


class CoachResult(BaseModel):
    coaching: List[CoachInsight]


# ─── Refactor output ──────────────────────────────────────────────────────────

class RefactorChange(BaseModel):
    issue_id: str
    change_description: str


class RefactorResult(BaseModel):
    refactored_code: str
    changes_made: List[RefactorChange]
    confidence: float = Field(..., ge=0.0, le=1.0)


# ─── Validator output ─────────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    correctness_score: int = Field(..., ge=0, le=100)
    logic_preserved: bool
    issues_addressed: int = Field(..., ge=0, le=100)
    flags: List[str]
    recommend_regenerate: bool


# ─── Final pipeline output ────────────────────────────────────────────────────

class ReviewResponse(BaseModel):
    status: str = "success"
    language: str
    analysis: AnalysisResult
    coaching: CoachResult
    refactor: RefactorResult
    validation: ValidationResult
    processing_time_seconds: float


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
    detail: Optional[str] = None
