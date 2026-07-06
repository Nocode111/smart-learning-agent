from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Integer, DateTime, ForeignKey, Index, JSON, Numeric, UniqueConstraint
from app.database import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    overall_level = Column(String(64))
    weak_points_json = Column(JSON)
    preference_json = Column(JSON)
    active_summary_json = Column(JSON)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uk_student_course"),
    )


class StudentKnowledgeMastery(Base):
    __tablename__ = "student_knowledge_mastery"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    knowledge_point_id = Column(BigInteger, ForeignKey("knowledge_points.id"), nullable=False)
    mastery_score = Column(Numeric(5, 2), nullable=False, default=0)
    correct_count = Column(Integer, nullable=False, default=0)
    wrong_count = Column(Integer, nullable=False, default=0)
    ask_count = Column(Integer, nullable=False, default=0)
    unresolved_count = Column(Integer, nullable=False, default=0)
    resource_view_count = Column(Integer, nullable=False, default=0)
    completed_task_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("student_id", "knowledge_point_id", name="uk_student_point"),
        Index("idx_mastery_student_course", "student_id", "course_id"),
        Index("idx_mastery_score", "mastery_score"),
    )
