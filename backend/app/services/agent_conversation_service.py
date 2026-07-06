from datetime import datetime

from sqlalchemy.orm import Session

from app.models.agent_conversation import AgentConversation, AgentMessage


class AgentConversationService:
    def get_or_create_conversation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        conversation_id: int | None = None,
        first_message: str | None = None,
    ) -> AgentConversation:
        if conversation_id:
            conversation = (
                db.query(AgentConversation)
                .filter(
                    AgentConversation.id == conversation_id,
                    AgentConversation.student_id == student_id,
                    AgentConversation.course_id == course_id,
                    AgentConversation.status == "active",
                )
                .first()
            )
            if not conversation:
                raise ValueError("会话不存在或无权访问")
            return conversation

        title = self.build_title(first_message)
        conversation = AgentConversation(
            student_id=student_id,
            course_id=course_id,
            title=title,
            status="active",
            message_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(conversation)
        db.flush()
        return conversation

    def get_conversation_by_id(
        self,
        db: Session,
        student_id: int,
        conversation_id: int,
    ) -> AgentConversation:
        conversation = (
            db.query(AgentConversation)
            .filter(
                AgentConversation.id == conversation_id,
                AgentConversation.student_id == student_id,
                AgentConversation.status == "active",
            )
            .first()
        )
        if not conversation:
            raise ValueError("会话不存在或无权访问")
        return conversation

    def get_recent_conversation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
    ) -> AgentConversation | None:
        return (
            db.query(AgentConversation)
            .filter(
                AgentConversation.student_id == student_id,
                AgentConversation.course_id == course_id,
                AgentConversation.status == "active",
            )
            .order_by(AgentConversation.updated_at.desc())
            .first()
        )

    def build_title(self, first_message: str | None) -> str | None:
        if not first_message:
            return None
        text = first_message.strip()
        return text[:30] if len(text) <= 30 else text[:30] + "..."

    def add_message(
        self,
        db: Session,
        conversation: AgentConversation,
        role: str,
        content: str | None,
        message_type: str = "text",
        intent: str | None = None,
        qa_id: int | None = None,
        document_id: int | None = None,
        related_knowledge_point_ids: list[int] | None = None,
        agent_steps: list[dict] | None = None,
        retrieved_chunks: list[dict] | None = None,
        metadata: dict | None = None,
        # 二期：消息状态与任务关联
        status: str = "completed",
        task_id: int | None = None,
        client_request_id: str | None = None,
        error_message: str | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            conversation_id=conversation.id,
            student_id=conversation.student_id,
            course_id=conversation.course_id,
            role=role,
            message_type=message_type,
            content=content,
            intent=intent,
            qa_id=qa_id,
            document_id=document_id,
            related_knowledge_point_ids=related_knowledge_point_ids,
            agent_steps_json=agent_steps,
            retrieved_chunks_json=retrieved_chunks,
            metadata_json=metadata,
            status=status,
            task_id=task_id,
            client_request_id=client_request_id,
            error_message=error_message,
            created_at=datetime.utcnow(),
        )
        db.add(message)

        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.updated_at = datetime.utcnow()
        db.flush()
        return message

    def get_recent_messages(
        self,
        db: Session,
        conversation_id: int,
        limit: int = 10,
    ) -> list[AgentMessage]:
        messages = (
            db.query(AgentMessage)
            .filter(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(messages))

    def update_memory(
        self,
        db: Session,
        conversation: AgentConversation,
        last_topic: str | None = None,
        last_knowledge_point_ids: list[int] | None = None,
        pending_action: dict | None = None,
        clear_pending: bool = False,
    ) -> AgentConversation:
        if last_topic is not None:
            conversation.last_topic = last_topic
        if last_knowledge_point_ids is not None:
            conversation.last_knowledge_point_ids = last_knowledge_point_ids
        if clear_pending:
            conversation.pending_action_json = None
        elif pending_action is not None:
            conversation.pending_action_json = pending_action
        conversation.updated_at = datetime.utcnow()
        db.flush()
        return conversation


agent_conversation_service = AgentConversationService()
