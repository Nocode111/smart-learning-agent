from datetime import datetime
from pydantic import BaseModel, Field


class PracticeQuestionPayload(BaseModel):
    question_no: int
    question_type: str = "single_choice"
    stem: str
    options: dict | None = None
    answered: bool = False


class PracticeQuestionInternalPayload(PracticeQuestionPayload):
    correct_answer: str
    explanation: str | None = None


class PracticeSessionPayload(BaseModel):
    session_id: int
    topic: str | None = None
    status: str
    question_count: int
    answered_count: int
    correct_count: int
    current_question_no: int | None = None


class PracticeGenerateResult(BaseModel):
    session: PracticeSessionPayload
    questions: list[PracticeQuestionPayload]


class PracticeGradeResult(BaseModel):
    session_id: int
    question_no: int
    submitted_answer: str
    normalized_answer: str | None = None
    is_correct: bool
    correct_answer: str
    feedback_text: str
    completed: bool = False
