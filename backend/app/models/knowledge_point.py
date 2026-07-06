from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Index
from app.database import Base


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    parent_id = Column(BigInteger, ForeignKey("knowledge_points.id"))
    name = Column(String(128), nullable=False)
    description = Column(Text)
    difficulty = Column(Integer, nullable=False, default=1)
    sort_order = Column(Integer, nullable=False, default=0)
    source = Column(String(32), nullable=False, default="manual")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_course_id", "course_id"),
        Index("idx_parent_id", "parent_id"),
    )
