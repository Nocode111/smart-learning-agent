from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Text

from app.database import Base


class GeneratedExerciseDocument(Base):
    __tablename__ = "generated_exercise_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    knowledge_point_id = Column(BigInteger)
    title = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    question_count = Column(Integer, nullable=False)
    difficulty = Column(String(32))
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    preview_content = Column(Text(length=4294967295))
    agent_steps_json = Column(JSON)
    status = Column(String(32), nullable=False, default="completed")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_generated_doc_user_id", "user_id"),
        Index("idx_generated_doc_course_id", "course_id"),
        Index("idx_generated_doc_knowledge_point_id", "knowledge_point_id"),
        Index("idx_generated_doc_created_at", "created_at"),
    )
