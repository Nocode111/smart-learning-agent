from pydantic import BaseModel
from datetime import datetime


class TaskResponse(BaseModel):
    id: int
    plan_id: int
    task_type: str
    title: str
    target_id: int | None = None
    estimated_minutes: int | None = None
    status: str
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class PlanResponse(BaseModel):
    id: int
    student_id: int
    course_id: int
    title: str
    reason: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    tasks: list[TaskResponse] = []

    class Config:
        from_attributes = True


class GenerateRequest(BaseModel):
    student_id: int
    course_id: int
    knowledge_point_id: int
