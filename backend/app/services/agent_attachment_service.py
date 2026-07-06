"""
对话附件服务 — 上传、抽取、索引、检索、删除。

文档参考：docs/智能答疑对话附件系统方案_详细技术实现文档.md Section 10
"""

import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.document_extract_service import document_extract_service
from app.services.rag_service import rag_service

UPLOAD_DIR = Path("uploads/agent_attachments")

ALLOWED_DOCUMENT_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".pptx"}
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20MB


class AgentAttachmentService:
    """对话附件服务"""

    # ── 文件名校验与安全处理 ──────────────────────────────────

    @staticmethod
    def _safe_file_name(original_filename: str) -> str:
        """只保留中文、英文字母、数字、点、下划线、连字符"""
        safe = "".join(
            c for c in original_filename
            if c.isalnum() or c in "._-" or "一" <= c <= "鿿"
        )
        if not safe or safe.startswith("."):
            safe = "uploaded_file"
        return safe

    @staticmethod
    def _is_allowed_file(file_name: str) -> bool:
        suffix = os.path.splitext(file_name)[1].lower()
        return suffix in ALLOWED_DOCUMENT_SUFFIXES

    @staticmethod
    def _get_mime_type(file_name: str) -> str:
        suffix = os.path.splitext(file_name)[1].lower()
        mime_map = {
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        return mime_map.get(suffix, "application/octet-stream")

    @staticmethod
    def _remove_suffix(filename: str) -> str:
        """去掉文件后缀作为默认标题"""
        return os.path.splitext(filename)[0]

    # ── 文件保存 ──────────────────────────────────────────────

    @staticmethod
    def _save_file(
        file_content: bytes,
        original_filename: str,
        student_id: int,
        conversation_id: int,
    ) -> tuple[str, str, int]:
        """
        保存上传文件到附件专用目录。
        路径：uploads/agent_attachments/{student_id}/{conversation_id}/{uuid}/{safe_name}
        返回 (file_path, stored_file_name, file_size)
        """
        safe_name = AgentAttachmentService._safe_file_name(original_filename)
        sub_dir = UPLOAD_DIR / str(student_id) / str(conversation_id) / uuid.uuid4().hex[:12]
        sub_dir.mkdir(parents=True, exist_ok=True)

        file_path = sub_dir / safe_name
        file_path.write_bytes(file_content)

        return str(file_path), safe_name, len(file_content)

    # ── 校验文件 ──────────────────────────────────────────────

    @classmethod
    def validate_file(cls, file) -> None:
        """校验文件类型和大小，失败抛出 ValueError"""
        if not cls._is_allowed_file(file.filename):
            raise ValueError(
                f"不支持的文件类型。允许：{', '.join(ALLOWED_DOCUMENT_SUFFIXES)}"
            )
        # 读取文件内容检查大小
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > MAX_ATTACHMENT_SIZE:
            raise ValueError(f"文件大小不能超过 20MB")

    # ── 计算内容哈希 ──────────────────────────────────────────

    @staticmethod
    def _hash_content(content: str) -> str:
        if not content:
            return ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    # ── 上传主流程（文档 Section 10.4） ────────────────────────

    def upload_attachment(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        conversation_id: int | None,
        file,
        title: str | None = None,
        auto_index: bool = True,
    ) -> dict:
        """
        上传附件完整流程：
        1. 获取或创建会话
        2. 校验文件
        3. 保存文件
        4. 创建附件记录
        5. 抽取文本
        6. 建立向量索引
        7. 写入会话消息
        8. 写入消息附件关系
        """
        from app.models.agent_attachment import AgentAttachment, AgentAttachmentChunk, AgentMessageAttachment
        from app.services.agent_conversation_service import agent_conversation_service

        # 1. 获取或创建会话
        conversation = agent_conversation_service.get_or_create_conversation(
            db=db,
            student_id=student_id,
            course_id=course_id,
            conversation_id=conversation_id,
            first_message=f"上传文件：{file.filename}",
        )

        # 2. 校验文件
        self.validate_file(file)

        # 3. 保存文件
        file_content = file.file.read()
        file_path, stored_file_name, file_size = self._save_file(
            file_content=file_content,
            original_filename=file.filename,
            student_id=student_id,
            conversation_id=conversation.id,
        )

        file_ext = os.path.splitext(file.filename)[1].lower()
        mime_type = self._get_mime_type(file.filename)

        # 4. 创建附件记录
        attachment = AgentAttachment(
            conversation_id=conversation.id,
            student_id=student_id,
            course_id=course_id,
            title=title or self._remove_suffix(file.filename),
            original_file_name=file.filename,
            stored_file_name=stored_file_name,
            file_ext=file_ext,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            attachment_type="document",
            extract_status="pending",
            index_status="none",
            status="active",
        )
        db.add(attachment)
        db.flush()

        # 5. 抽取文本
        try:
            content = document_extract_service.extract_text(file_path, mime_type, file.filename)
            attachment.content = content
            attachment.content_hash = self._hash_content(content)
            attachment.extract_status = "extracted"
        except Exception as e:
            attachment.extract_status = "failed"
            attachment.extract_error = str(e)
            content = None

        # 6. 建立向量索引
        if auto_index and content:
            try:
                attachment.index_status = "pending"
                db.flush()

                chunk_records = self._index_attachment(
                    db=db,
                    attachment=attachment,
                    content=content,
                )
                attachment.index_status = "indexed"
                attachment.chunk_count = len(chunk_records)
            except Exception as e:
                attachment.index_status = "failed"
                attachment.index_error = str(e)
        elif not content:
            attachment.index_status = "failed"
            attachment.index_error = "文本抽取失败，无法建立索引"

        # 7. 写入会话消息
        upload_message = agent_conversation_service.add_message(
            db=db,
            conversation=conversation,
            role="user",
            content=f"我上传了附件《{attachment.title}》。",
            message_type="attachment_upload",
            metadata={
                "attachments": [self._serialize_attachment(attachment)]
            },
        )
        attachment.upload_message_id = upload_message.id

        # 8. 写入消息附件关系
        db.add(AgentMessageAttachment(
            message_id=upload_message.id,
            attachment_id=attachment.id,
            relation_type="uploaded",
        ))

        db.commit()
        db.refresh(attachment)

        return {
            "conversation": conversation,
            "attachment": attachment,
            "upload_message": upload_message,
        }

    # ── 索引附件 ──────────────────────────────────────────────

    def _index_attachment(
        self,
        db: Session,
        attachment,
        content: str,
    ) -> list:
        """索引附件文本：调用 RAG 服务 + 写入 chunk 记录"""
        from app.models.agent_attachment import AgentAttachmentChunk

        chunks = rag_service.index_attachment(
            attachment_id=attachment.id,
            conversation_id=attachment.conversation_id,
            student_id=attachment.student_id,
            course_id=attachment.course_id,
            title=attachment.title,
            file_name=attachment.original_file_name,
            content=content,
        )

        chunk_records = []
        for chunk in chunks:
            chunk_record = AgentAttachmentChunk(
                attachment_id=attachment.id,
                conversation_id=attachment.conversation_id,
                student_id=attachment.student_id,
                course_id=attachment.course_id,
                chunk_index=int(chunk["vector_id"].rsplit("_", 1)[-1]),
                vector_id=chunk["vector_id"],
                content=chunk["content"],
                char_count=len(chunk["content"]),
                metadata_json=chunk["metadata"],
            )
            db.add(chunk_record)
            chunk_records.append(chunk_record)

        db.flush()
        return chunk_records

    # ── 查询当前会话附件 ──────────────────────────────────────

    def list_active_attachments(
        self,
        db: Session,
        conversation_id: int,
        student_id: int,
        course_id: int,
        limit: int = 20,
    ) -> list:
        """查询当前会话的有效附件（仅返回 active + indexed，文档 Section 7.4）"""
        from app.models.agent_attachment import AgentAttachment

        return (
            db.query(AgentAttachment)
            .filter(
                AgentAttachment.conversation_id == conversation_id,
                AgentAttachment.student_id == student_id,
                AgentAttachment.course_id == course_id,
                AgentAttachment.status == "active",
                AgentAttachment.index_status == "indexed",
            )
            .order_by(AgentAttachment.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_attachment(
        self,
        db: Session,
        attachment_id: int,
        student_id: int,
        require_active: bool = False,
    ) -> object | None:
        """获取单个附件（带权限校验）

        require_active=True: 仅返回 active 状态的附件（用于上传/下载/预览）
        require_active=False: 返回任意状态的附件（用于删除后状态检查等）
        """
        from app.models.agent_attachment import AgentAttachment

        q = (
            db.query(AgentAttachment)
            .filter(
                AgentAttachment.id == attachment_id,
                AgentAttachment.student_id == student_id,
            )
        )
        if require_active:
            q = q.filter(AgentAttachment.status == "active")
        return q.first()

    # ── 删除附件（二期完整版：文档 Section 7） ─────────────────

    def remove_attachment(
        self,
        db: Session,
        attachment_id: int,
        student_id: int,
        delete_physical_file: bool = False,
        reason: str = "user_removed",
    ) -> dict:
        """
        完整附件移除流程：
        1. 查询附件 → 状态校验
        2. 状态改为 deleting → 删除 Chroma 向量
        3. chunk 标记 deleted → 可选删除物理文件
        4. 附件状态改为 removed → 更新上传消息 metadata
        5. 写入 attachment_removed 消息
        """
        from app.models.agent_attachment import AgentAttachment, AgentAttachmentChunk
        from app.services.agent_conversation_service import agent_conversation_service

        attachment = (
            db.query(AgentAttachment)
            .filter(
                AgentAttachment.id == attachment_id,
                AgentAttachment.student_id == student_id,
            )
            .first()
        )
        if not attachment:
            raise ValueError("附件不存在或无权访问")
        if attachment.status not in ("active", "delete_failed"):
            return {
                "attachment": attachment,
                "message": None,
                "already_removed": True,
            }

        conversation = agent_conversation_service.get_conversation_by_id(
            db=db,
            student_id=student_id,
            conversation_id=attachment.conversation_id,
        )

        attachment.status = "deleting"
        db.flush()

        try:
            # 删除 Chroma 向量
            rag_service.delete_attachment_vectors(attachment_id)

            # chunk 标记 deleted
            db.query(AgentAttachmentChunk).filter(
                AgentAttachmentChunk.attachment_id == attachment_id
            ).update({
                "status": "deleted",
                "deleted_at": datetime.utcnow(),
            }, synchronize_session=False)

            # 可选删除物理文件
            if delete_physical_file and os.path.isfile(attachment.file_path):
                os.remove(attachment.file_path)
                attachment.physical_file_deleted = 1

            attachment.status = "removed"
            attachment.index_status = "removed"
            attachment.deleted_at = datetime.utcnow()
            attachment.deleted_by = student_id
            attachment.delete_reason = reason
            attachment.delete_error = None

            # 更新上传消息 metadata
            self._mark_upload_message_attachment_removed(db, attachment)

            # 写入 attachment_removed 消息
            remove_message = agent_conversation_service.add_message(
                db=db,
                conversation=conversation,
                role="system",
                content=f"已移除附件「{attachment.title}」。",
                message_type="attachment_removed",
                metadata={
                    "attachment_id": attachment.id,
                    "title": attachment.title,
                },
            )
            attachment.delete_message_id = remove_message.id

            db.commit()
            return {
                "attachment": attachment,
                "message": remove_message,
                "already_removed": False,
            }

        except Exception as e:
            attachment.status = "delete_failed"
            attachment.delete_error = str(e)
            db.commit()
            raise

    def _mark_upload_message_attachment_removed(self, db, attachment):
        """更新上传消息 metadata_json 中的附件状态（文档 Section 7.3）"""
        from app.models.agent_conversation import AgentMessage

        if not attachment.upload_message_id:
            return

        msg = db.query(AgentMessage).filter(
            AgentMessage.id == attachment.upload_message_id,
            AgentMessage.student_id == attachment.student_id,
        ).first()
        if not msg or not msg.metadata_json:
            return

        metadata = msg.metadata_json or {}
        attachments = metadata.get("attachments") or []
        for item in attachments:
            if int(item.get("id", 0)) == int(attachment.id):
                item["status"] = "removed"
                item["index_status"] = "removed"
                item["removed_at"] = attachment.deleted_at.isoformat() if attachment.deleted_at else None
                item["removed"] = True

        msg.metadata_json = metadata
        msg.status = "completed"
        db.flush()

    def delete_attachment(
        self,
        db: Session,
        attachment_id: int,
        student_id: int,
    ) -> None:
        """[兼容旧接口] 软删除附件 + 清理向量，内部调用 remove_attachment"""
        self.remove_attachment(
            db=db,
            attachment_id=attachment_id,
            student_id=student_id,
            delete_physical_file=False,
            reason="user_removed",
        )

    # ── 重建索引 ──────────────────────────────────────────────

    def reindex_attachment(
        self,
        db: Session,
        attachment_id: int,
        student_id: int,
    ) -> object:
        """重建附件向量索引"""
        from app.models.agent_attachment import AgentAttachment, AgentAttachmentChunk

        attachment = (
            db.query(AgentAttachment)
            .filter(
                AgentAttachment.id == attachment_id,
                AgentAttachment.student_id == student_id,
                AgentAttachment.status == "active",
            )
            .first()
        )
        if not attachment:
            raise ValueError("附件不存在或无权访问")
        if not attachment.content:
            raise ValueError("附件文本为空，无法重建索引")

        # 删除旧向量和 chunk 记录
        rag_service.delete_attachment_vectors(attachment_id)
        db.query(AgentAttachmentChunk).filter(
            AgentAttachmentChunk.attachment_id == attachment_id
        ).delete()

        # 重建索引
        attachment.index_status = "pending"
        db.flush()

        try:
            chunk_records = self._index_attachment(
                db=db,
                attachment=attachment,
                content=attachment.content,
            )
            attachment.index_status = "indexed"
            attachment.chunk_count = len(chunk_records)
            attachment.index_error = None
        except Exception as e:
            attachment.index_status = "failed"
            attachment.index_error = str(e)

        db.commit()
        db.refresh(attachment)
        return attachment

    # ── 序列化附件 ────────────────────────────────────────────

    @staticmethod
    def _serialize_attachment(attachment) -> dict:
        return {
            "id": attachment.id,
            "title": attachment.title,
            "original_file_name": attachment.original_file_name,
            "file_ext": attachment.file_ext,
            "file_size": attachment.file_size,
            "attachment_type": attachment.attachment_type,
            "extract_status": attachment.extract_status,
            "index_status": attachment.index_status,
            "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
        }

    def serialize_for_context(self, attachment) -> dict:
        """序列化附件用于 Agent 上下文（不含全文）"""
        return {
            "id": attachment.id,
            "title": attachment.title,
            "file_name": attachment.original_file_name,
            "file_ext": attachment.file_ext,
            "extract_status": attachment.extract_status,
            "index_status": attachment.index_status,
            "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
        }


agent_attachment_service = AgentAttachmentService()
