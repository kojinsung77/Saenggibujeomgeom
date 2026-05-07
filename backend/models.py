"""Pydantic v2 models for request/response payloads and SSE events."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- Upload / DB build ----------

class UploadResponse(BaseModel):
    file_id: str
    area: str
    filename: str
    size: int


class DBBuildRequest(BaseModel):
    # area key -> file_id (uploaded earlier)
    file_ids: dict[str, str]


class DBBuildResponse(BaseModel):
    status: str
    students: int
    records_per_area: dict[str, int]


class DBStatusResponse(BaseModel):
    exists: bool
    students: int = 0
    records: dict[str, int] = Field(default_factory=dict)
    last_built_at: Optional[str] = None


# ---------- Students / Search ----------

class StudentSummary(BaseModel):
    id: int
    grade: int
    class_no: int
    number: int
    name: str
    areas: dict[str, bool]


class RecordDetail(BaseModel):
    area: str
    content: str
    subject: Optional[str] = None
    grade_year: Optional[int] = None
    semester: Optional[int] = None
    record_id: Optional[int] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class StudentDetailsResponse(BaseModel):
    student: StudentSummary
    records: list[RecordDetail]


class SearchHit(BaseModel):
    record_id: int
    student_id: int
    student_name: str
    grade: int
    class_no: int
    number: int
    area: str
    snippet: str


# ---------- Gemini / Prompt ----------

class GeminiConnectRequest(BaseModel):
    api_key: str


class GeminiConnectResponse(BaseModel):
    ok: bool = True
    models: list[str]


class PromptResponse(BaseModel):
    prompt_text: str
    updated_at: str


class PromptUpdate(BaseModel):
    prompt_text: str


# ---------- Inspection ----------

class InspectionStartRequest(BaseModel):
    areas: list[str]
    model: str
    batch_size: int = 3
    grade: Optional[int] = None
    class_no: Optional[int] = None
    student_ids: Optional[list[int]] = None


class InspectionStartResponse(BaseModel):
    inspection_id: int


class InspectionSummary(BaseModel):
    id: int
    started_at: str
    completed_at: Optional[str]
    status: str
    model: str
    batch_size: int
    total_records: int
    violations: int


class ResultRow(BaseModel):
    id: int
    inspection_id: int
    student_id: int
    student_name: str
    grade: int
    class_no: int
    number: int
    area: str
    record_id: int
    violation: bool
    category: Optional[str] = None
    reason: Optional[str] = None
    evidence: Optional[str] = None
    suggested_text: Optional[str] = None
    processed_at: Optional[str] = None


# ---------- SSE event payloads ----------

class ProgressEvent(BaseModel):
    processed: int
    total: int
    current_student: Optional[str] = None
    current_area: Optional[str] = None
    eta_sec: Optional[float] = None


class ResultEvent(BaseModel):
    student_id: int
    student_name: str
    grade: int
    class_no: int
    number: int
    area: str
    record_id: int
    violation: bool
    category: Optional[str] = None
    reason: Optional[str] = None
    evidence: Optional[str] = None
    suggested_text: Optional[str] = None


class DoneEvent(BaseModel):
    inspection_id: int
    total_violations: int
    total_normal: int
    duration_sec: float


class ErrorEvent(BaseModel):
    message: str
    detail: Optional[str] = None
