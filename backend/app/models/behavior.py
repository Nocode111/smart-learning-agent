from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Index
from app.database import Base


class LearningBehavior(Base):
    __tablename__ = "learning_behaviors"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    course_id = Column(BigInteger, ForeignKey("courses.id"))
    knowledge_point_id = Column(BigInteger, ForeignKey("knowledge_points.id"))
    behavior_type = Column(String(64), nullable=False, comment="ask_question/qa_feedback/answer_question/view_resource/complete_task/generate_exercise")
    content = Column(Text)
    result = Column(String(64))
    duration_seconds = Column(Integer)
    source = Column(String(64))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_behavior_student_id", "student_id"),
        Index("idx_behavior_course_point", "course_id", "knowledge_point_id"),
        Index("idx_behavior_type", "behavior_type"),
        Index("idx_behavior_created_at", "created_at"),
    )
