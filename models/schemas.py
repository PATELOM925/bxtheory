from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator


Confidence = Literal["high", "medium", "low"]


class FileRef(BaseModel):
    sha256: str
    filename: str
    local_path: str
    gemini_file_id: str
    kind: str
    uploaded_at: str


class TopicSpec(BaseModel):
    topic_id: str
    label: str
    chapter_start: int | None = None
    chapter_end: int | None = None
    priority: float = 1.0


class CourseSpec(BaseModel):
    course_code: str
    exam_name: str = "Midterm 1"
    exam_date: str | None = None
    topics: list[TopicSpec] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    confidence: Confidence = "low"

    @field_validator("exam_date")
    @classmethod
    def _validate_exam_date(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        date.fromisoformat(value)
        return value


class UserConstraints(BaseModel):
    start_date: str
    hours_weekday: float = 3.0
    hours_weekend: float = 6.0
    priority_weights: dict[str, float] = Field(default_factory=dict)
    familiarity_by_course: dict[str, float] = Field(default_factory=dict)
    coverage_by_course: dict[str, float] = Field(default_factory=dict)
    weakness_by_course: dict[str, float] = Field(default_factory=dict)
    notes: str = ""
    timezone: str | None = None

    @field_validator("start_date")
    @classmethod
    def _validate_start_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator(
        "priority_weights",
        "familiarity_by_course",
        "coverage_by_course",
        "weakness_by_course",
        mode="before",
    )
    @classmethod
    def _coerce_float_dict(cls, value: object) -> dict[str, float]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object.")

        normalized: dict[str, float] = {}
        for key, raw in value.items():
            normalized[str(key)] = float(raw)
        return normalized

    @field_validator("coverage_by_course")
    @classmethod
    def _clamp_coverage(cls, value: dict[str, float]) -> dict[str, float]:
        return {course: min(100.0, max(0.0, amount)) for course, amount in value.items()}

    @field_validator("familiarity_by_course", "weakness_by_course")
    @classmethod
    def _clamp_likert_scores(cls, value: dict[str, float]) -> dict[str, float]:
        return {course: min(5.0, max(1.0, score)) for course, score in value.items()}


class TopicEstimate(BaseModel):
    course_code: str
    topic_id: str
    estimated_hours: float
    confidence: Confidence
    basis: str


class PlanRow(BaseModel):
    date: str
    course_code: str
    task_type: str
    topic_id: str
    topic_label: str
    hours: float
    notes: str = ""

    @field_validator("date")
    @classmethod
    def _validate_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class PlanSummary(BaseModel):
    total_hours: float
    hours_by_course: dict[str, float] = Field(default_factory=dict)
    feasible: bool
    warnings: list[str] = Field(default_factory=list)
