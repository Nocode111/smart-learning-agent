from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Index
from app.database import Base


class LearningResource(Base):
    __tablename__ = "learning_resources"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    knowledge_point_id = Column(BigInteger, ForeignKey("knowledge_points.id"))
    title = Column(String(255), nullable=False)
    resource_type = Column(String(32), nullable=False, comment="text/pdf/video/link")
    content = Column(Text(length=4294967295))  # LONGTEXT
    file_url = Column(String(512))
    owner_id = Column(BigInteger, ForeignKey("users.id"))
    file_name = Column(String(255))
    file_path = Column(String(512))
    file_size = Column(BigInteger)
    mime_type = Column(String(128))
    indexed = Column(Integer, nullable=False, default=0)
    index_status = Column(String(32), nullable=False, default="none")
    index_error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_resource_course_id", "course_id"),
        Index("idx_resource_knowledge_point_id", "knowledge_point_id"),
    )
