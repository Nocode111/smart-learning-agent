from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.agent_memory import (
    AgentMemory,
    AgentMemoryEvent,
    AgentMemoryFeedback,
    AgentMemorySummary,
)


ACTIVE_STATUS = "active"
VALID_MEMORY_TYPES = {
    "profile",
    "preference",
    "learning_state",
    "episodic",
    "semantic",
    "procedural",
}
VALID_MEMORY_STATUSES = {"active", "disabled", "deleted", "expired", "superseded"}


class AgentLongTermMemoryService:
    """长期记忆基础服务。

    第三阶段只负责自建 memory tables 的 CRUD、检索和上下文组装。
    自动抽取记忆由后续 LangMem 阶段接入。
    """

    # ================================================================
    # 记忆 CRUD
    # ================================================================

    def create_memory(
        self,
        db: Session,
        student_id: int,
        course_id: int | None,
        memory_type: str,
        memory_key: str,
        memory_text: str,
        memory_value_json=None,
        confidence: float = 0.8,
        importance: float = 0.5,
        source_type: str | None = None,
        source_id: int | None = None,
        expires_at: datetime | None = None,
        reason: str | None = None,
        source_message_id: int | None = None,
        source_task_id: int | None = None,
    ) -> AgentMemory:
        memory_type = self._validate_memory_type(memory_type)
        memory_key = self._validate_memory_key(memory_key)
        memory_text = self._validate_memory_text(memory_text)

        memory = AgentMemory(
            student_id=student_id,
            course_id=course_id,
            memory_type=memory_type,
            memory_key=memory_key,
            memory_value_json=memory_value_json,
            memory_text=memory_text,
            confidence=self._clamp(confidence),
            importance=self._clamp(importance),
            status=ACTIVE_STATUS,
            source_type=source_type,
            source_id=source_id,
            expires_at=expires_at,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(memory)
        db.flush()
        self._add_event(
            db=db,
            memory=memory,
            event_type="created",
            new_value_json=self._snapshot(memory),
            reason=reason or ("manual_create" if not source_type else f"source:{source_type}"),
            source_message_id=source_message_id,
            source_task_id=source_task_id,
        )
        db.flush()
        return memory

    def find_active_memory_by_key(
        self,
        db: Session,
        student_id: int,
        course_id: int | None,
        memory_type: str,
        memory_key: str,
    ) -> AgentMemory | None:
        memory_type = self._validate_memory_type(memory_type)
        memory_key = self._validate_memory_key(memory_key)
        query = db.query(AgentMemory).filter(
            AgentMemory.student_id == student_id,
            AgentMemory.memory_type == memory_type,
            AgentMemory.memory_key == memory_key,
            AgentMemory.status == ACTIVE_STATUS,
        )
        if course_id is None:
            query = query.filter(AgentMemory.course_id.is_(None))
        else:
            query = query.filter(AgentMemory.course_id == course_id)
        return query.order_by(AgentMemory.updated_at.desc()).first()

    def upsert_memory(
        self,
        db: Session,
        student_id: int,
        course_id: int | None,
        memory_type: str,
        memory_key: str,
        memory_text: str,
        memory_value_json=None,
        confidence: float = 0.8,
        importance: float = 0.5,
        source_type: str | None = None,
        source_id: int | None = None,
        expires_at: datetime | None = None,
        reason: str = "auto_extract",
        source_message_id: int | None = None,
        source_task_id: int | None = None,
    ) -> AgentMemory:
        memory_type = self._validate_memory_type(memory_type)
        memory_key = self._validate_memory_key(memory_key)
        memory_text = self._validate_memory_text(memory_text)
        confidence = self._clamp(confidence)
        importance = self._clamp(importance)

        memory = self.find_active_memory_by_key(
            db=db,
            student_id=student_id,
            course_id=course_id,
            memory_type=memory_type,
            memory_key=memory_key,
        )
        if not memory:
            return self.create_memory(
                db=db,
                student_id=student_id,
                course_id=course_id,
                memory_type=memory_type,
                memory_key=memory_key,
                memory_text=memory_text,
                memory_value_json=memory_value_json,
                confidence=confidence,
                importance=importance,
                source_type=source_type,
                source_id=source_id,
                expires_at=expires_at,
                reason=reason,
                source_message_id=source_message_id,
                source_task_id=source_task_id,
            )

        old_snapshot = self._snapshot(memory)
        memory.memory_text = memory_text
        memory.memory_value_json = memory_value_json
        memory.confidence = max(memory.confidence or 0.0, confidence)
        memory.importance = max(memory.importance or 0.0, importance)
        memory.source_type = source_type or memory.source_type
        memory.source_id = source_id or memory.source_id
        memory.expires_at = expires_at
        memory.updated_at = datetime.utcnow()
        db.flush()

        event_type = "reinforced" if old_snapshot == self._snapshot(memory) else "updated"
        self._add_event(
            db=db,
            memory=memory,
            event_type=event_type,
            old_value_json=old_snapshot,
            new_value_json=self._snapshot(memory),
            reason=reason,
            source_message_id=source_message_id,
            source_task_id=source_task_id,
        )
        db.flush()
        return memory

    def list_memories(
        self,
        db: Session,
        student_id: int,
        course_id: int | None = None,
        memory_type: str | None = None,
        status: str = ACTIVE_STATUS,
        q: str | None = None,
        include_global: bool = True,
        limit: int = 50,
    ) -> list[AgentMemory]:
        query = db.query(AgentMemory).filter(AgentMemory.student_id == student_id)

        if course_id is not None:
            if include_global:
                query = query.filter(
                    or_(AgentMemory.course_id == course_id, AgentMemory.course_id.is_(None))
                )
            else:
                query = query.filter(AgentMemory.course_id == course_id)

        if memory_type:
            query = query.filter(AgentMemory.memory_type == self._validate_memory_type(memory_type))

        if status:
            query = query.filter(AgentMemory.status == status)

        if q:
            like = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    AgentMemory.memory_key.like(like),
                    AgentMemory.memory_text.like(like),
                )
            )

        return (
            query.order_by(
                AgentMemory.importance.desc(),
                AgentMemory.confidence.desc(),
                AgentMemory.updated_at.desc(),
            )
            .limit(max(1, min(limit, 200)))
            .all()
        )

    def get_memory(self, db: Session, memory_id: int, student_id: int) -> AgentMemory:
        memory = (
            db.query(AgentMemory)
            .filter(AgentMemory.id == memory_id, AgentMemory.student_id == student_id)
            .first()
        )
        if not memory:
            raise ValueError("记忆不存在或无权访问")
        return memory

    def update_memory(
        self,
        db: Session,
        memory_id: int,
        student_id: int,
        **updates,
    ) -> AgentMemory:
        memory = self.get_memory(db, memory_id, student_id)
        old_snapshot = self._snapshot(memory)

        if "memory_type" in updates and updates["memory_type"] is not None:
            memory.memory_type = self._validate_memory_type(updates["memory_type"])
        if "memory_key" in updates and updates["memory_key"] is not None:
            memory.memory_key = self._validate_memory_key(updates["memory_key"])
        if "memory_text" in updates and updates["memory_text"] is not None:
            memory.memory_text = self._validate_memory_text(updates["memory_text"])
        if "memory_value_json" in updates:
            memory.memory_value_json = updates["memory_value_json"]
        if "confidence" in updates and updates["confidence"] is not None:
            memory.confidence = self._clamp(updates["confidence"])
        if "importance" in updates and updates["importance"] is not None:
            memory.importance = self._clamp(updates["importance"])
        if "course_id" in updates:
            memory.course_id = updates["course_id"]
        if "status" in updates and updates["status"] is not None:
            memory.status = self._validate_status(updates["status"])
        if "expires_at" in updates:
            memory.expires_at = updates["expires_at"]

        memory.updated_at = datetime.utcnow()
        db.flush()
        event_type = "updated"
        if old_snapshot.get("status") != memory.status:
            if memory.status == "disabled":
                event_type = "disabled"
            elif memory.status == "deleted":
                event_type = "deleted"
            elif memory.status == "expired":
                event_type = "expired"
            elif memory.status == "superseded":
                event_type = "superseded"
        self._add_event(
            db=db,
            memory=memory,
            event_type=event_type,
            old_value_json=old_snapshot,
            new_value_json=self._snapshot(memory),
            reason=updates.get("reason") or "manual_update",
            source_message_id=updates.get("source_message_id"),
            source_task_id=updates.get("source_task_id"),
        )
        db.flush()
        return memory

    def disable_memory(
        self,
        db: Session,
        memory_id: int,
        student_id: int,
        reason: str = "manual_disable",
    ) -> AgentMemory:
        return self.update_memory(
            db=db,
            memory_id=memory_id,
            student_id=student_id,
            status="disabled",
            reason=reason,
        )

    def delete_memory(
        self,
        db: Session,
        memory_id: int,
        student_id: int,
        reason: str = "manual_delete",
    ) -> AgentMemory:
        return self.update_memory(
            db=db,
            memory_id=memory_id,
            student_id=student_id,
            status="deleted",
            reason=reason,
        )

    # ================================================================
    # 事件 / 反馈 / 摘要
    # ================================================================

    def list_events(
        self,
        db: Session,
        student_id: int,
        memory_id: int | None = None,
        limit: int = 50,
    ) -> list[AgentMemoryEvent]:
        query = db.query(AgentMemoryEvent).filter(AgentMemoryEvent.student_id == student_id)
        if memory_id:
            query = query.filter(AgentMemoryEvent.memory_id == memory_id)
        return query.order_by(AgentMemoryEvent.created_at.desc()).limit(max(1, min(limit, 200))).all()

    def record_policy_rejection(
        self,
        db: Session,
        student_id: int,
        course_id: int | None,
        candidate_json,
        reason: str,
        source_message_id: int | None = None,
        source_task_id: int | None = None,
    ) -> AgentMemoryEvent:
        event = AgentMemoryEvent(
            memory_id=None,
            student_id=student_id,
            course_id=course_id,
            event_type="policy_rejected",
            source_message_id=source_message_id,
            source_task_id=source_task_id,
            old_value_json=None,
            new_value_json=candidate_json,
            reason=reason,
            created_at=datetime.utcnow(),
        )
        db.add(event)
        db.flush()
        return event

    def add_feedback(
        self,
        db: Session,
        memory_id: int,
        student_id: int,
        action: str,
        feedback_text: str | None = None,
    ) -> AgentMemoryFeedback:
        memory = self.get_memory(db, memory_id, student_id)
        feedback = AgentMemoryFeedback(
            memory_id=memory.id,
            student_id=student_id,
            action=(action or "").strip(),
            feedback_text=feedback_text,
            created_at=datetime.utcnow(),
        )
        db.add(feedback)
        self._add_event(
            db=db,
            memory=memory,
            event_type="feedback",
            new_value_json={"action": feedback.action, "feedback_text": feedback.feedback_text},
            reason="user_feedback",
        )
        db.flush()
        return feedback

    def create_summary(
        self,
        db: Session,
        student_id: int,
        course_id: int | None,
        conversation_id: int | None,
        summary_type: str,
        summary_text: str,
        covered_message_ids_json: list[int] | None = None,
        related_knowledge_point_ids_json: list[int] | None = None,
    ) -> AgentMemorySummary:
        summary_text = self._validate_memory_text(summary_text)
        summary = AgentMemorySummary(
            student_id=student_id,
            course_id=course_id,
            conversation_id=conversation_id,
            summary_type=(summary_type or "conversation").strip(),
            summary_text=summary_text,
            covered_message_ids_json=covered_message_ids_json or [],
            related_knowledge_point_ids_json=related_knowledge_point_ids_json or [],
            status=ACTIVE_STATUS,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(summary)
        db.flush()
        return summary

    # ================================================================
    # Agent 上下文检索
    # ================================================================

    def build_memory_context(
        self,
        db: Session,
        student_id: int,
        course_id: int | None = None,
        message: str | None = None,
        per_type_limit: int = 5,
    ) -> dict:
        memories = self.list_memories(
            db=db,
            student_id=student_id,
            course_id=course_id,
            status=ACTIVE_STATUS,
            q=None,
            include_global=True,
            limit=100,
        )
        if message:
            memories = self._rank_memories(memories, message)

        grouped = {memory_type: [] for memory_type in VALID_MEMORY_TYPES}
        for memory in memories:
            if memory.memory_type in grouped and len(grouped[memory.memory_type]) < per_type_limit:
                grouped[memory.memory_type].append(memory)

        selected = [item for group in grouped.values() for item in group]
        if selected:
            now = datetime.utcnow()
            for memory in selected:
                memory.last_used_at = now
            db.flush()

        return {
            "profile_memories": grouped["profile"],
            "preference_memories": grouped["preference"],
            "learning_state_memories": grouped["learning_state"],
            "episodic_memories": grouped["episodic"],
            "semantic_memories": grouped["semantic"],
            "procedural_memories": grouped["procedural"],
            "memory_context_text": self.format_memory_context(grouped),
        }

    @staticmethod
    def format_memory_context(grouped: dict[str, list[AgentMemory]]) -> str:
        labels = {
            "profile": "用户画像记忆",
            "preference": "用户偏好记忆",
            "learning_state": "学习状态记忆",
            "episodic": "历史事件记忆",
            "semantic": "语义总结记忆",
            "procedural": "回答策略记忆",
        }
        parts = []
        for memory_type, label in labels.items():
            items = grouped.get(memory_type) or []
            if not items:
                continue
            lines = [f"- {item.memory_text}" for item in items]
            parts.append(f"【{label}】\n" + "\n".join(lines))
        return "\n\n".join(parts)

    # ================================================================
    # 内部工具
    # ================================================================

    def _add_event(
        self,
        db: Session,
        memory: AgentMemory,
        event_type: str,
        old_value_json=None,
        new_value_json=None,
        reason: str | None = None,
        source_message_id: int | None = None,
        source_task_id: int | None = None,
    ) -> AgentMemoryEvent:
        event = AgentMemoryEvent(
            memory_id=memory.id,
            student_id=memory.student_id,
            course_id=memory.course_id,
            event_type=event_type,
            source_message_id=source_message_id,
            source_task_id=source_task_id,
            old_value_json=old_value_json,
            new_value_json=new_value_json,
            reason=reason,
            created_at=datetime.utcnow(),
        )
        db.add(event)
        return event

    @staticmethod
    def _snapshot(memory: AgentMemory) -> dict:
        return {
            "id": memory.id,
            "course_id": memory.course_id,
            "memory_type": memory.memory_type,
            "memory_key": memory.memory_key,
            "memory_value_json": memory.memory_value_json,
            "memory_text": memory.memory_text,
            "confidence": memory.confidence,
            "importance": memory.importance,
            "status": memory.status,
            "source_type": memory.source_type,
            "source_id": memory.source_id,
            "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
        }

    @staticmethod
    def _rank_memories(memories: list[AgentMemory], message: str) -> list[AgentMemory]:
        text = (message or "").lower()
        if not text:
            return memories

        def score(memory: AgentMemory) -> float:
            base = (memory.importance or 0) + (memory.confidence or 0)
            haystack = f"{memory.memory_key} {memory.memory_text}".lower()
            bonus = 0.0
            for token in {item for item in text.replace("，", " ").replace("。", " ").split() if item}:
                if token and token in haystack:
                    bonus += 0.5
            return base + bonus

        return sorted(memories, key=score, reverse=True)

    @staticmethod
    def _validate_memory_type(memory_type: str) -> str:
        normalized = (memory_type or "").strip()
        if normalized not in VALID_MEMORY_TYPES:
            raise ValueError(f"不支持的记忆类型：{memory_type}")
        return normalized

    @staticmethod
    def _validate_status(status: str) -> str:
        normalized = (status or "").strip()
        if normalized not in VALID_MEMORY_STATUSES:
            raise ValueError(f"不支持的记忆状态：{status}")
        return normalized

    @staticmethod
    def _validate_memory_key(memory_key: str) -> str:
        normalized = (memory_key or "").strip()
        if not normalized:
            raise ValueError("memory_key 不能为空")
        if len(normalized) > 128:
            raise ValueError("memory_key 不能超过 128 个字符")
        return normalized

    @staticmethod
    def _validate_memory_text(memory_text: str) -> str:
        normalized = (memory_text or "").strip()
        if not normalized:
            raise ValueError("memory_text 不能为空")
        return normalized

    @staticmethod
    def _clamp(value: float | int | None) -> float:
        if value is None:
            return 0.0
        return max(0.0, min(float(value), 1.0))


agent_long_term_memory_service = AgentLongTermMemoryService()
