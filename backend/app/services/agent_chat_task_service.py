"""
提问任务服务 — 创建任务、查询任务、取消任务、状态机管理。

文档参考：docs/附件删除与提问取消二期完整版_详细技术实现文档.md Section 11
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.agent_chat_task import AgentChatTask
from app.models.agent_conversation import AgentMessage
from app.services.course_permission_service import course_permission_service


class AgentTaskCanceled(Exception):
    """任务被取消的异常"""
    pass


class AgentChatTaskService:
    """提问任务服务"""

    # ── 创建任务（文档 Section 11.2） ────────────────────────

    def create_task(
        self,
        db: Session,
        current_user,
        course_id: int,
        conversation_id: int | None,
        message: str,
        attachment_ids: list[int] | None = None,
        client_request_id: str | None = None,
    ) -> AgentChatTask:
        from app.services.agent_conversation_service import agent_conversation_service

        # 权限校验
        course_permission_service.require_view_course(db, current_user, course_id)

        # 幂等检查
        client_request_id = client_request_id or uuid.uuid4().hex[:16]
        existing = self.find_by_client_request_id(db, current_user.id, client_request_id)
        if existing:
            return existing

        # 获取或创建会话
        conversation = agent_conversation_service.get_or_create_conversation(
            db=db,
            student_id=current_user.id,
            course_id=course_id,
            conversation_id=conversation_id,
            first_message=message,
        )

        # 创建用户消息
        user_message = agent_conversation_service.add_message(
            db=db,
            conversation=conversation,
            role="user",
            content=message,
            message_type="text",
            status="completed",
            client_request_id=client_request_id,
        )

        # 创建 AI 占位消息
        assistant_message = agent_conversation_service.add_message(
            db=db,
            conversation=conversation,
            role="assistant",
            content="",
            message_type="answer",
            status="pending",
            client_request_id=client_request_id,
        )

        attachment_ids = attachment_ids or []

        # 创建任务记录
        task = AgentChatTask(
            task_uuid=f"task_{uuid.uuid4().hex[:16]}",
            client_request_id=client_request_id,
            conversation_id=conversation.id,
            student_id=current_user.id,
            course_id=course_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            request_message=message,
            request_payload_json={
                "attachment_ids": attachment_ids,
            },
            status="queued",
            stage="created",
        )
        db.add(task)
        db.flush()

        # 关联 assistant message 到 task
        assistant_message.task_id = task.id
        db.commit()
        db.refresh(task)

        return task

    # ── 查询任务 ──────────────────────────────────────────

    def get_task(self, db: Session, task_uuid: str) -> AgentChatTask | None:
        return db.query(AgentChatTask).filter(AgentChatTask.task_uuid == task_uuid).first()

    def get_task_or_404(self, db: Session, task_uuid: str, student_id: int) -> AgentChatTask:
        task = db.query(AgentChatTask).filter(
            AgentChatTask.task_uuid == task_uuid,
            AgentChatTask.student_id == student_id,
        ).first()
        if not task:
            raise ValueError("任务不存在或无权访问")
        return task

    def find_by_client_request_id(
        self, db: Session, student_id: int, client_request_id: str
    ) -> AgentChatTask | None:
        return db.query(AgentChatTask).filter(
            AgentChatTask.student_id == student_id,
            AgentChatTask.client_request_id == client_request_id,
        ).first()

    # ── 任务状态变更 ──────────────────────────────────────

    def mark_running(self, db: Session, task: AgentChatTask, stage: str = "building_context"):
        db.refresh(task)
        if task.cancel_requested or task.status in ("cancel_requested", "canceled"):
            raise AgentTaskCanceled()
        if task.status in ("completed", "failed"):
            raise ValueError("任务已结束，不能重新运行")

        task.status = "running"
        task.stage = stage
        task.started_at = datetime.utcnow()
        if task.assistant_message_id:
            db.query(AgentMessage).filter(
                AgentMessage.id == task.assistant_message_id,
                AgentMessage.status.in_(["pending", "running"]),
            ).update({"status": "running"}, synchronize_session=False)
        db.commit()
        db.refresh(task)

    def mark_stage(self, db: Session, task: AgentChatTask, stage: str, progress_text: str = ""):
        db.refresh(task)
        if task.cancel_requested or task.status in ("cancel_requested", "canceled"):
            raise AgentTaskCanceled()

        task.stage = stage
        if progress_text:
            task.progress_text = progress_text
        db.commit()
        db.refresh(task)

    def mark_completed(self, db: Session, task: AgentChatTask, result: dict | None = None):
        db.commit()
        db.refresh(task)
        if task.cancel_requested or task.status in ("cancel_requested", "canceled"):
            raise AgentTaskCanceled()

        task.status = "completed"
        task.stage = "done"
        task.finished_at = datetime.utcnow()
        if result:
            task.result_json = result
        # 更新 assistant message
        if task.assistant_message_id:
            update_values = {"status": "completed"}
            if result and result.get("answer") is not None:
                update_values["content"] = result.get("answer")
            if result and result.get("type") is not None:
                update_values["message_type"] = result.get("type")
            if result and result.get("intent") is not None:
                update_values["intent"] = result.get("intent")
            if result and result.get("qa_id") is not None:
                update_values["qa_id"] = result.get("qa_id")
            if result and result.get("document_id") is not None:
                update_values["document_id"] = result.get("document_id")
            if result and result.get("related_knowledge_point_ids") is not None:
                update_values["related_knowledge_point_ids"] = result.get("related_knowledge_point_ids")
            if result and result.get("agent_steps") is not None:
                update_values["agent_steps_json"] = result.get("agent_steps")
            if result and result.get("retrieved_chunks") is not None:
                update_values["retrieved_chunks_json"] = result.get("retrieved_chunks")
            if result and result.get("metadata") is not None:
                update_values["metadata_json"] = result.get("metadata")

            db.query(AgentMessage).filter(
                AgentMessage.id == task.assistant_message_id,
                AgentMessage.status != "canceled",
            ).update(update_values, synchronize_session=False)
        db.commit()
        db.refresh(task)

    def mark_failed(self, db: Session, task: AgentChatTask, error: str):
        db.refresh(task)
        if task.cancel_requested or task.status in ("cancel_requested", "canceled"):
            self.mark_canceled(db, task)
            return

        task.status = "failed"
        task.failed_at = datetime.utcnow()
        task.error_message = error
        # 更新 assistant message
        if task.assistant_message_id:
            db.query(AgentMessage).filter(
                AgentMessage.id == task.assistant_message_id,
            ).update({
                "status": "failed",
                "error_message": error,
                "content": "生成失败，请重新提问。",
            }, synchronize_session=False)
        db.commit()
        db.refresh(task)

    def mark_canceled(self, db: Session, task: AgentChatTask):
        if not task:
            return
        task.status = "canceled"
        task.canceled_at = datetime.utcnow()
        # 更新 assistant message — 仅当消息状态为 pending/running 时
        if task.assistant_message_id:
            db.query(AgentMessage).filter(
                AgentMessage.id == task.assistant_message_id,
                AgentMessage.status.in_(["pending", "running", "canceled"]),
            ).update({
                "status": "canceled",
                "content": "本次提问已停止。",
                "canceled_at": datetime.utcnow(),
            }, synchronize_session=False)
        db.commit()
        db.refresh(task)

    # ── 取消任务（文档 Section 11.4） ───────────────────────

    def request_cancel(self, db: Session, task_uuid: str, student_id: int, reason: str = "user_stop") -> AgentChatTask:
        """请求取消任务。只设置 cancel_requested，真正取消由 runner 完成。"""
        task = self.get_task_or_404(db, task_uuid, student_id)

        if task.status in ("canceled",):
            return task  # 已取消

        if task.status in ("completed", "failed"):
            return task  # 已结束任务视为取消请求幂等成功，前端据此收尾即可

        if task.status == "cancel_requested":
            return task  # 已是取消请求状态，幂等

        task.cancel_requested = 1
        task.status = "cancel_requested"
        task.cancel_reason = reason
        task.cancel_requested_at = datetime.utcnow()
        if task.assistant_message_id:
            db.query(AgentMessage).filter(
                AgentMessage.id == task.assistant_message_id,
                AgentMessage.status.in_(["pending", "running", "canceled"]),
            ).update({
                "status": "canceled",
                "content": "本次提问已停止。",
                "canceled_at": datetime.utcnow(),
            }, synchronize_session=False)
        db.commit()
        db.refresh(task)
        return task

    def is_cancel_requested(self, db: Session, task: AgentChatTask) -> bool:
        """检查任务是否被请求取消（文档 Section 11.4）"""
        db.refresh(task)
        return bool(task.cancel_requested) or task.status in ("cancel_requested", "canceled")

    # ── 超时清理（文档 Section 14.7） ──────────────────────

    def cleanup_stale_tasks(self, db: Session, timeout_minutes: int = 5):
        """将长时间未更新的 running 任务标记为 failed/timeout"""
        cutoff = datetime.utcnow()
        # Simple approach: mark old running tasks
        stale = db.query(AgentChatTask).filter(
            AgentChatTask.status.in_(["running", "queued"]),
            AgentChatTask.updated_at < cutoff,
        ).all()
        # This is a placeholder — real implementation would use timedelta
        return stale


agent_chat_task_service = AgentChatTaskService()
