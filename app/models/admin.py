"""
Pydantic models for Platform Admin API request validation.

All request bodies are validated against these models before
reaching the service layer.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserStatusValue(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserRole(str, Enum):
    STUDENT = "student"
    RECRUITER = "recruiter"
    COMPANY_ADMIN = "company_admin"
    UNIVERSITY_ADMIN = "university_admin"
    UNIVERSITY = "university"
    ADMIN = "admin"


class FlagAction(str, Enum):
    DISMISS = "dismiss"
    REMOVE_CONTENT = "remove_content"
    SUSPEND_AUTHOR = "suspend_author"
    ESCALATE = "escalate"


class ExportType(str, Enum):
    STUDENTS = "students"
    COMPANIES = "companies"
    JOBS = "jobs"
    APPLICATIONS = "applications"
    VERIFICATIONS = "verifications"
    ANALYTICS = "analytics"


class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class UserStatusUpdate(BaseModel):
    status: UserStatusValue
    reason: str = Field(..., min_length=1)
    notify_user: bool = True


class UserRoleUpdate(BaseModel):
    role: UserRole
    reason: str = Field(..., min_length=1)

    @field_validator("role")
    @classmethod
    def role_not_admin(cls, v):
        """Prevent promotion to admin through this endpoint."""
        if v == UserRole.ADMIN:
            raise ValueError("Cannot assign admin role through this endpoint")
        return v


class CompanyApproval(BaseModel):
    note: Optional[str] = None


class CompanyRejection(BaseModel):
    reason: str = Field(..., min_length=1)
    note: Optional[str] = None


class UniversityApproval(BaseModel):
    note: Optional[str] = None


class UniversityRejection(BaseModel):
    reason: str = Field(..., min_length=1)
    note: Optional[str] = None


class FlagResolution(BaseModel):
    action: FlagAction
    note: Optional[str] = None


class AIWeights(BaseModel):
    skill_alignment: int = Field(..., ge=0, le=100)
    research_similarity: int = Field(..., ge=0, le=100)
    language_readiness: int = Field(..., ge=0, le=100)
    learning_trajectory: int = Field(..., ge=0, le=100)

    @model_validator(mode="after")
    def weights_sum_to_100(self):
        total = (
            self.skill_alignment
            + self.research_similarity
            + self.language_readiness
            + self.learning_trajectory
        )
        if total != 100:
            raise ValueError(f"Weights must sum to 100, got {total}")
        return self


class AIConfigUpdate(BaseModel):
    default_weights: Optional[AIWeights] = None
    min_score_threshold: Optional[int] = Field(None, ge=0, le=100)
    max_candidates_per_run: Optional[int] = Field(None, ge=1)
    model_version: Optional[str] = None


class ExportFilters(BaseModel):
    university_id: Optional[str] = None
    company_id: Optional[str] = None
    verification_status: Optional[str] = None
    graduation_year: Optional[int] = None
    status: Optional[str] = None


class ExportRequest(BaseModel):
    type: ExportType
    filters: Optional[ExportFilters] = None
    format: ExportFormat = ExportFormat.CSV
    notify_email: Optional[str] = None
