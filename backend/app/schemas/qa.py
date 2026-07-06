from pydantic import BaseModel
from datetime import datetime


class AskRequest(BaseModel):
    student_id: int
    course_id: int
    question: str


class AskResponse(BaseModel):
    qa_id: int
    answer: str
    related_knowledge_point_ids: list[int] = []
    retrieved_chunks: list[dict] = []
    agent_steps: list[dict] = []
    next_suggestion: str | None = None


class FeedbackRequest(BaseModel):
    resolved: bool
    comment: str | None = None


class QARecordResponse(BaseModel):
    id: int
    student_id: int
    course_id: int
    question: str
    answer: str
    related_knowledge_points: list | None = None
    resolved: int | None = None
    feedback_comment: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
