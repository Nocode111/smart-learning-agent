from pydantic import BaseModel
from datetime import datetime


class KnowledgeMasteryItem(BaseModel):
    knowledge_point_id: int
    name: str
    mastery_score: float
    status: str


class WeakPointItem(BaseModel):
    knowledge_point_id: int
    name: str
    mastery_score: float
    status: str
    reason: str


class ProfileResponse(BaseModel):
    student_id: int
    course_id: int
    overall_level: str | None = None
    knowledge_mastery: list[KnowledgeMasteryItem] = []
    weak_points: list[WeakPointItem] = []
    updated_at: datetime | None = None
