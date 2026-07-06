from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Float, Index, JSON, String, Text

from app.database import Base


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger)

    memory_type = Column(String(32), nullable=False)
    memory_key = Column(String(128), nullable=False)
    memory_value_json = Column(JSON)
    memory_text = Column(Text, nullable=False)

    confidence = Column(Float, nullable=False, default=0.8)
    importance = Column(Float, nullable=False, default=0.5)
    status = Column(String(32), nullable=False, default="active")

    source_type = Column(String(64))
    source_id = Column(BigInteger)
    last_used_at = Column(DateTime)
    expires_at = Column(DateTime)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_memory_student_course", "student_id", "course_id"),
        Index("idx_agent_memory_type", "memory_type"),
        Index("idx_agent_memory_key", "memory_key"),
        Index("idx_agent_memory_status", "status"),
        Index("idx_agent_memory_importance", "importance"),
        Index("idx_agent_memory_last_used", "last_used_at"),
    )


class AgentMemoryEvent(Base):
    __tablename__ = "agent_memory_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    memory_id = Column(BigInteger)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger)

    event_type = Column(String(32), nullable=False)
    source_message_id = Column(BigInteger)
    source_task_id = Column(BigInteger)
    old_value_json = Column(JSON)
    new_value_json = Column(JSON)
    reason = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_memory_event_memory", "memory_id"),
        Index("idx_agent_memory_event_student_course", "student_id", "course_id"),
        Index("idx_agent_memory_event_type", "event_type"),
        Index("idx_agent_memory_event_created", "created_at"),
    )


class AgentMemorySummary(Base):
    __tablename__ = "agent_memory_summaries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger)
    conversation_id = Column(BigInteger)

    summary_type = Column(String(32), nullable=False, default="conversation")
    summary_text = Column(Text, nullable=False)
    covered_message_ids_json = Column(JSON)
    related_knowledge_point_ids_json = Column(JSON)
    status = Column(String(32), nullable=False, default="active")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_memory_summary_student_course", "student_id", "course_id"),
        Index("idx_agent_memory_summary_conversation", "conversation_id"),
        Index("idx_agent_memory_summary_type", "summary_type"),
        Index("idx_agent_memory_summary_status", "status"),
    )


class AgentMemoryFeedback(Base):
    __tablename__ = "agent_memory_feedback"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    memory_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)

    action = Column(String(32), nullable=False)
    feedback_text = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_memory_feedback_memory", "memory_id"),
        Index("idx_agent_memory_feedback_student", "student_id"),
        Index("idx_agent_memory_feedback_action", "action"),
    )
