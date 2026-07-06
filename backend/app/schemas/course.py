from pydantic import BaseModel
from datetime import datetime


class CourseCreate(BaseModel):
    name: str
    description: str | None = None
    teacher_id: int | None = None


class StudentCourseCreate(BaseModel):
    name: str
    description: str | None = None
    learning_goal: str | None = None
    auto_generate_outline: bool = True


class CourseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class CourseResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    teacher_id: int | None = None
    course_type: str = "teacher"
    owner_id: int | None = None
    visibility: str = "public"
    source: str = "manual"
    status: str = "active"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CourseOutlineGenerateRequest(BaseModel):
    course_id: int
    learning_goal: str | None = None
    overwrite_existing: bool = False


class CourseOutlineGenerateResponse(BaseModel):
    course_id: int
    knowledge_points: list["KnowledgePointResponse"]


class KnowledgePointCreate(BaseModel):
    course_id: int
    parent_id: int | None = None
    name: str
    description: str | None = None
    difficulty: int = 1
    sort_order: int = 0


class KnowledgePointUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    difficulty: int | None = None
    sort_order: int | None = None


class KnowledgePointResponse(BaseModel):
    id: int
    course_id: int
    parent_id: int | None = None
    name: str
    description: str | None = None
    difficulty: int
    sort_order: int
    source: str = "manual"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
