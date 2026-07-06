from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Text

from app.database import Base


class AgentChatTask(Base):
    __tablename__ = "agent_chat_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_uuid = Column(String(64), nullable=False, unique=True)
    client_request_id = Column(String(64), nullable=False)

    conversation_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    user_message_id = Column(BigInteger, nullable=False)
    assistant_message_id = Column(BigInteger)

    request_message = Column(Text(length=4294967295), nullable=False)
    request_payload_json = Column(JSON)

    status = Column(String(32), nullable=False, default="queued")
    stage = Column(String(64))
    progress_text = Column(String(255))

    cancel_requested = Column(Integer, nullable=False, default=0)
    cancel_reason = Column(String(255))
    cancel_requested_at = Column(DateTime)
    canceled_at = Column(DateTime)

    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    failed_at = Column(DateTime)
    error_message = Column(Text)

    result_json = Column(JSON)
    debug_json = Column(JSON)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_chat_task_conversation", "conversation_id"),
        Index("idx_agent_chat_task_student_course", "student_id", "course_id"),
        Index("idx_agent_chat_task_status", "status"),
        Index("idx_agent_chat_task_created_at", "created_at"),
    )
