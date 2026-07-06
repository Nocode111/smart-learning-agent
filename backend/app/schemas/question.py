from pydantic import BaseModel
from datetime import datetime


class QuestionCreate(BaseModel):
    course_id: int
    knowledge_point_id: int
    question_type: str = "single"
    stem: str
    options_json: dict | None = None
    answer: str
    explanation: str | None = None
    difficulty: int = 1


class QuestionResponse(BaseModel):
    id: int
    course_id: int
    knowledge_point_id: int
    question_type: str
    stem: str
    options_json: dict | None = None
    answer: str
    explanation: str | None = None
    difficulty: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubmitAnswerRequest(BaseModel):
    student_id: int
    answer: str


class SubmitAnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: str | None = None
