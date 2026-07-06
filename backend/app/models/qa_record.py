from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Index, JSON
from app.database import Base


class QARecord(Base):
    __tablename__ = "qa_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text(length=4294967295), nullable=False)  # LONGTEXT
    related_knowledge_points = Column(JSON)
    retrieved_chunks = Column(JSON)
    resolved = Column(Integer)
    feedback_comment = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_qa_student_id", "student_id"),
        Index("idx_qa_course_id", "course_id"),
        Index("idx_qa_created_at", "created_at"),
    )
