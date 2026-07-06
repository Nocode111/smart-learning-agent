from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Text

from app.database import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    title = Column(String(255))
    status = Column(String(32), nullable=False, default="active")
    last_topic = Column(String(255))
    last_knowledge_point_ids = Column(JSON)
    pending_action_json = Column(JSON)
    context_summary_json = Column(JSON)
    message_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_conv_student_course", "student_id", "course_id"),
        Index("idx_agent_conv_status", "status"),
        Index("idx_agent_conv_updated_at", "updated_at"),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    role = Column(String(32), nullable=False)
    message_type = Column(String(32), nullable=False, default="text")
    content = Column(Text(length=4294967295))
    intent = Column(String(64))
    qa_id = Column(BigInteger)
    document_id = Column(BigInteger)
    related_knowledge_point_ids = Column(JSON)
    agent_steps_json = Column(JSON)
    retrieved_chunks_json = Column(JSON)
    metadata_json = Column(JSON)

    # 二期：消息状态与任务关联
    status = Column(String(32), nullable=False, default="completed")
    task_id = Column(BigInteger)
    client_request_id = Column(String(64))
    canceled_at = Column(DateTime)
    error_message = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_msg_conversation_id", "conversation_id"),
        Index("idx_agent_msg_student_course", "student_id", "course_id"),
        Index("idx_agent_msg_created_at", "created_at"),
        Index("idx_agent_msg_status", "status"),
        Index("idx_agent_msg_task_id", "task_id"),
        Index("idx_agent_msg_client_request_id", "client_request_id"),
    )
