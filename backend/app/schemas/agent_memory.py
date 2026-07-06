from datetime import datetime

from pydantic import BaseModel, Field


class AgentMemoryCreateRequest(BaseModel):
    course_id: int | None = None
    memory_type: str
    memory_key: str
    memory_text: str
    memory_value_json: dict | list | str | int | float | bool | None = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source_type: str | None = None
    source_id: int | None = None
    expires_at: datetime | None = None


class AgentMemoryUpdateRequest(BaseModel):
    course_id: int | None = None
    memory_type: str | None = None
    memory_key: str | None = None
    memory_text: str | None = None
    memory_value_json: dict | list | str | int | float | bool | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = None
    expires_at: datetime | None = None
    reason: str | None = None


class AgentMemoryFeedbackRequest(BaseModel):
    action: str
    feedback_text: str | None = None


class AgentMemoryResponse(BaseModel):
    id: int
    student_id: int
    course_id: int | None
    memory_type: str
    memory_key: str
    memory_value_json: dict | list | str | int | float | bool | None
    memory_text: str
    confidence: float
    importance: float
    status: str
    source_type: str | None
    source_id: int | None
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentMemoryListResponse(BaseModel):
    items: list[AgentMemoryResponse]


class AgentMemoryEventResponse(BaseModel):
    id: int
    memory_id: int | None
    student_id: int
    course_id: int | None
    event_type: str
    source_message_id: int | None
    source_task_id: int | None
    old_value_json: dict | list | str | int | float | bool | None
    new_value_json: dict | list | str | int | float | bool | None
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentMemorySummaryCreateRequest(BaseModel):
    course_id: int | None = None
    conversation_id: int | None = None
    summary_type: str = "conversation"
    summary_text: str
    covered_message_ids_json: list[int] = Field(default_factory=list)
    related_knowledge_point_ids_json: list[int] = Field(default_factory=list)


class AgentMemorySummaryResponse(BaseModel):
    id: int
    student_id: int
    course_id: int | None
    conversation_id: int | None
    summary_type: str
    summary_text: str
    covered_message_ids_json: list[int] | None
    related_knowledge_point_ids_json: list[int] | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentMemoryContextResponse(BaseModel):
    profile_memories: list[AgentMemoryResponse] = Field(default_factory=list)
    preference_memories: list[AgentMemoryResponse] = Field(default_factory=list)
    learning_state_memories: list[AgentMemoryResponse] = Field(default_factory=list)
    episodic_memories: list[AgentMemoryResponse] = Field(default_factory=list)
    semantic_memories: list[AgentMemoryResponse] = Field(default_factory=list)
    procedural_memories: list[AgentMemoryResponse] = Field(default_factory=list)
    memory_context_text: str = ""
