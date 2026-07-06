"""Bridge authoritative learning profiles with long-term memories.

StudentProfile and StudentKnowledgeMastery remain the source of truth for
course learning state. Long-term memories add user-stated preferences,
recent learning episodes, and qualitative notes that should not overwrite
mastery scores directly.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


class AgentProfileMemoryBridgeService:
    def build_context(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        memory_context: dict | None = None,
    ) -> dict:
        from app.services.profile_service import profile_service

        profile = profile_service.get_profile_for_agent(db, student_id, course_id)
        memory_context = memory_context or {}
        supplements = self._build_memory_supplements(memory_context)

        merged = {
            **profile,
            "source_of_truth": {
                "overall_level": "student_profiles",
                "weak_points": "student_knowledge_mastery",
                "knowledge_mastery": "student_knowledge_mastery",
                "preferences": "agent_memories",
                "recent_learning_events": "agent_memories",
                "qualitative_learning_state": "agent_memories",
            },
            "memory_supplements": supplements,
        }
        return {
            "learning_profile": profile,
            "learning_profile_with_memory": merged,
            "learning_profile_memory_context_text": self.format_context_text(merged),
        }

    def _build_memory_supplements(self, memory_context: dict) -> dict:
        return {
            "preferences": self._serialize_memories(memory_context.get("preference_memories") or []),
            "qualitative_learning_state": self._serialize_memories(memory_context.get("learning_state_memories") or []),
            "recent_learning_events": self._serialize_memories(memory_context.get("episodic_memories") or []),
            "procedures": self._serialize_memories(memory_context.get("procedural_memories") or []),
        }

    @staticmethod
    def _serialize_memories(memories: list) -> list[dict]:
        serialized = []
        for memory in memories:
            serialized.append(
                {
                    "id": getattr(memory, "id", None),
                    "memory_type": getattr(memory, "memory_type", None),
                    "memory_key": getattr(memory, "memory_key", None),
                    "memory_text": getattr(memory, "memory_text", ""),
                    "memory_value_json": getattr(memory, "memory_value_json", None),
                    "confidence": getattr(memory, "confidence", None),
                    "importance": getattr(memory, "importance", None),
                    "course_id": getattr(memory, "course_id", None),
                }
            )
        return serialized

    @staticmethod
    def format_context_text(profile_with_memory: dict) -> str:
        lines = [
            "【学习画像权威数据】",
            f"- 整体水平：{profile_with_memory.get('overall_level', '未知')}",
            f"- 薄弱知识点：{profile_with_memory.get('weak_points') or []}",
            f"- 知识点掌握情况：{profile_with_memory.get('knowledge_mastery') or []}",
        ]

        supplements = profile_with_memory.get("memory_supplements") or {}
        labels = {
            "preferences": "长期记忆补充：学习偏好",
            "qualitative_learning_state": "长期记忆补充：学习状态自述",
            "recent_learning_events": "长期记忆补充：近期学习事件",
            "procedures": "长期记忆补充：回答策略",
        }
        for key, label in labels.items():
            items = supplements.get(key) or []
            if not items:
                continue
            lines.append(f"【{label}】")
            for item in items[:5]:
                text = item.get("memory_text") or ""
                if text:
                    lines.append(f"- {text}")

        lines.append("【数据边界】")
        lines.append("- 掌握度、薄弱点、整体水平以学习画像表为准；长期记忆只作为偏好和定性补充。")
        return "\n".join(lines)


agent_profile_memory_bridge_service = AgentProfileMemoryBridgeService()
