from datetime import datetime
from pydantic import BaseModel


class ExerciseGenerateRequest(BaseModel):
    course_id: int
    prompt: str
    question_count: int | None = None
    knowledge_point_id: int | None = None
    difficulty: str | None = "adaptive"
    include_answer: bool = True
    include_explanation: bool = True


class ExerciseGenerateResponse(BaseModel):
    id: int
    title: str
    file_name: str
    preview_content: str
    download_url: str
    agent_steps: list[dict]


class GeneratedExerciseDocumentResponse(BaseModel):
    id: int
    user_id: int
    course_id: int
    knowledge_point_id: int | None = None
    title: str
    prompt: str
    question_count: int
    difficulty: str | None = None
    file_name: str
    preview_content: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
