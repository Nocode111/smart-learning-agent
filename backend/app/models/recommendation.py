from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Index
from app.database import Base


class RecommendationPlan(Base):
    __tablename__ = "recommendation_plans"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    title = Column(String(255), nullable=False)
    reason = Column(Text)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_plan_student_id", "student_id"),
        Index("idx_plan_status", "status"),
    )


class RecommendationTask(Base):
    __tablename__ = "recommendation_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    plan_id = Column(BigInteger, ForeignKey("recommendation_plans.id"), nullable=False)
    task_type = Column(String(32), nullable=False, comment="resource/practice/qa/review")
    title = Column(String(255), nullable=False)
    target_id = Column(BigInteger)
    estimated_minutes = Column(Integer)
    status = Column(String(32), nullable=False, default="pending")
    completed_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_task_plan_id", "plan_id"),
        Index("idx_task_status", "status"),
    )
