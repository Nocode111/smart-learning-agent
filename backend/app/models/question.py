from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Index, JSON
from app.database import Base


class Question(Base):
    __tablename__ = "questions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    knowledge_point_id = Column(BigInteger, ForeignKey("knowledge_points.id"), nullable=False)
    question_type = Column(String(32), nullable=False, comment="single/multiple/judge/short")
    stem = Column(Text, nullable=False)
    options_json = Column(JSON)
    answer = Column(Text, nullable=False)
    explanation = Column(Text)
    difficulty = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_question_course_id", "course_id"),
        Index("idx_question_knowledge_point_id", "knowledge_point_id"),
    )


class QuestionAttempt(Base):
    __tablename__ = "question_attempts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    question_id = Column(BigInteger, ForeignKey("questions.id"), nullable=False)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    knowledge_point_id = Column(BigInteger, ForeignKey("knowledge_points.id"), nullable=False)
    submitted_answer = Column(Text)
    is_correct = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_attempt_student_id", "student_id"),
        Index("idx_attempt_question_id", "question_id"),
        Index("idx_attempt_knowledge_point_id", "knowledge_point_id"),
    )
