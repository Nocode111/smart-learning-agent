from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Text

from app.database import Base


class AgentAttachment(Base):
    __tablename__ = "agent_attachments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    upload_message_id = Column(BigInteger)

    title = Column(String(255), nullable=False)
    original_file_name = Column(String(255), nullable=False)
    stored_file_name = Column(String(255), nullable=False)
    file_ext = Column(String(32), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_size = Column(BigInteger, nullable=False, default=0)
    mime_type = Column(String(128))
    attachment_type = Column(String(32), nullable=False, default="document")

    content = Column(Text(length=4294967295))
    content_hash = Column(String(64))
    extract_status = Column(String(32), nullable=False, default="pending")
    extract_error = Column(Text)
    index_status = Column(String(32), nullable=False, default="none")
    index_error = Column(Text)
    chunk_count = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="active")

    # 二期：附件移除状态字段
    deleted_at = Column(DateTime)
    deleted_by = Column(BigInteger)
    delete_reason = Column(String(255))
    delete_error = Column(Text)
    physical_file_deleted = Column(Integer, nullable=False, default=0)
    delete_message_id = Column(BigInteger)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_attachment_conversation", "conversation_id"),
        Index("idx_agent_attachment_student_course", "student_id", "course_id"),
        Index("idx_agent_attachment_course", "course_id"),
        Index("idx_agent_attachment_status", "status"),
        Index("idx_agent_attachment_index_status", "index_status"),
        Index("idx_agent_attachment_created_at", "created_at"),
        Index("idx_agent_attachment_deleted_at", "deleted_at"),
        Index("idx_agent_attachment_deleted_by", "deleted_by"),
    )


class AgentAttachmentChunk(Base):
    __tablename__ = "agent_attachment_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    attachment_id = Column(BigInteger, nullable=False)
    conversation_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    vector_id = Column(String(128), nullable=False)
    content = Column(Text(length=4294967295), nullable=False)
    char_count = Column(Integer, nullable=False, default=0)
    metadata_json = Column(JSON)

    # 二期：chunk 状态
    status = Column(String(32), nullable=False, default="active")
    deleted_at = Column(DateTime)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_attachment_chunk_attachment", "attachment_id"),
        Index("idx_agent_attachment_chunk_conversation", "conversation_id"),
        Index("idx_agent_attachment_chunk_student_course", "student_id", "course_id"),
        Index("idx_agent_attachment_chunk_status", "status"),
        Index("idx_agent_attachment_chunk_deleted_at", "deleted_at"),
    )


class AgentMessageAttachment(Base):
    __tablename__ = "agent_message_attachments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(BigInteger, nullable=False)
    attachment_id = Column(BigInteger, nullable=False)
    relation_type = Column(String(32), nullable=False, default="referenced")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
