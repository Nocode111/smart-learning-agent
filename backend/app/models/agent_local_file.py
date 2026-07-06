"""
本地文件修改操作 SQLAlchemy Model（文档 Section 8）
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, String, Text

from app.database import Base


class AgentLocalFileOperation(Base):
    __tablename__ = "agent_local_file_operations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    operation_uuid = Column(String(64), nullable=False, unique=True)

    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger)
    conversation_id = Column(BigInteger)
    task_id = Column(BigInteger)
    user_message_id = Column(BigInteger)
    assistant_message_id = Column(BigInteger)

    status = Column(String(32), nullable=False, default="preview_ready")

    original_path = Column(Text, nullable=False)
    resolved_path = Column(Text, nullable=False)
    workspace_root = Column(Text, nullable=False)
    file_name = Column(String(255), nullable=False)
    file_ext = Column(String(32), nullable=False)
    file_size = Column(BigInteger, nullable=False, default=0)
    encoding = Column(String(64), nullable=False, default="utf-8")
    newline = Column(String(16))

    instruction = Column(Text, nullable=False)
    summary = Column(Text)

    original_sha256 = Column(String(64), nullable=False)
    proposed_sha256 = Column(String(64))
    applied_sha256 = Column(String(64))

    artifact_dir = Column(Text, nullable=False)
    original_snapshot_path = Column(Text)
    proposed_content_path = Column(Text)
    diff_path = Column(Text)
    backup_path = Column(Text)

    error_message = Column(Text)
    canceled_reason = Column(String(255))

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    confirmed_at = Column(DateTime)
    applied_at = Column(DateTime)
    canceled_at = Column(DateTime)
    restored_at = Column(DateTime)

    __table_args__ = (
        Index("idx_lfo_student", "student_id"),
        Index("idx_lfo_conversation", "conversation_id"),
        Index("idx_lfo_task", "task_id"),
        Index("idx_lfo_status", "status"),
        Index("idx_lfo_created_at", "created_at"),
    )
