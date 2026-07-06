from __future__ import annotations

from datetime import datetime
from typing import Literal
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    configured: bool
    missing: list[str] = Field(default_factory=list)
    available: bool
    init_error: str | None = None


class SearchRequest(BaseModel):
    student_id: int
    course_id: int | None = None
    query: str
    limit: int | None = None


class SearchResponse(BaseModel):
    enabled: bool = True
    available: bool
    group_ids: list[str] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    context_text: str = ""
    error: str | None = None


class MemoryEpisodeRequest(BaseModel):
    student_id: int
    course_id: int | None = None
    memory_id: int | None = None
    memory_type: str | None = None
    memory_key: str | None = None
    memory_text: str | None = None
    memory_value_json: Any | None = None
    confidence: float | None = None
    importance: float | None = None
    reference_time: datetime | None = None


class LearningEventEpisodeRequest(BaseModel):
    student_id: int
    course_id: int | None = None
    event_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reference_time: datetime | None = None


class EpisodeRequest(BaseModel):
    student_id: int
    course_id: int | None = None
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source_description: str = "smart-learning-agent episode"
    source_type: Literal["json", "text", "message", "fact_triple"] = "json"
    reference_time: datetime | None = None


class EpisodeWriteResponse(BaseModel):
    enabled: bool = True
    written: bool
    group_id: str | None = None
    episode_uuid: str | None = None
    reason: str | None = None
    error: str | None = None


class BuildIndicesResponse(BaseModel):
    ok: bool
    error: str | None = None
