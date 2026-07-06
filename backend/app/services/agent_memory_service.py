import re
from datetime import datetime, timedelta


class AgentMemoryService:
    def build_context(self, conversation, recent_messages: list) -> dict:
        """构建上下文，自动清理过期 pending_action（文档 Section 16.3）"""
        pending_action = conversation.pending_action_json
        if pending_action and self.is_pending_expired(pending_action):
            pending_action = None

        return {
            "conversation_id": conversation.id,
            "last_topic": conversation.last_topic,
            "last_knowledge_point_ids": conversation.last_knowledge_point_ids or [],
            "pending_action": pending_action,
            "recent_messages": [
                {
                    "role": msg.role,
                    "type": msg.message_type,
                    "content": msg.content,
                    "intent": msg.intent,
                    "related_knowledge_point_ids": msg.related_knowledge_point_ids,
                    "metadata": msg.metadata_json,
                }
                for msg in recent_messages
            ],
        }

    def is_affirmative(self, message: str) -> bool:
        normalized = (message or "").strip().lower().replace(" ", "")
        affirmative_words = [
            "需要", "要", "好的", "好", "可以", "行",
            "来", "来吧", "生成吧", "出吧", "给我出",
            "嗯", "嗯嗯", "开始吧", "继续",
        ]
        return normalized in affirmative_words

    def is_negative(self, message: str) -> bool:
        normalized = (message or "").strip().lower().replace(" ", "")
        negative_words = [
            "不需要", "不用", "不要", "先不用", "算了", "暂时不用",
        ]
        return normalized in negative_words

    def has_question_count(self, message: str) -> bool:
        return self.extract_question_count(message, default=0) > 0

    def extract_question_count(self, message: str, default: int = 5) -> int:
        match = re.search(r"(\d+)\s*[道个题]", message)
        if match:
            return max(1, min(int(match.group(1)), 20))

        chinese_map = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        for word, count in chinese_map.items():
            if f"{word}道" in message or f"{word}个" in message or f"{word}题" in message:
                return count

        return default

    def is_pending_expired(self, pending_action: dict) -> bool:
        created_at = pending_action.get("created_at")
        if not created_at:
            return False
        dt = datetime.fromisoformat(created_at)
        return datetime.utcnow() - dt > timedelta(minutes=30)

    def resolve_contextual_intent(self, message: str, context: dict) -> dict | None:
        """通用上下文意图解析，基于 pending_action 中的 confirm_intent / negative_intent"""
        pending_action = context.get("pending_action")
        if not pending_action:
            # 回退：分析上一条 assistant 消息
            return self.resolve_from_last_assistant_message(message, context)

        # 检查过期
        if self.is_pending_expired(pending_action):
            return None

        # 用户确认语 → 使用 pending_action 中的 confirm_intent
        if self.is_affirmative(message):
            return {
                "intent": pending_action.get("confirm_intent"),
                "source": "pending_action",
                "pending_action": pending_action,
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                "payload": pending_action.get("payload") or {},
            }

        # 用户否定语 → 使用 negative_intent
        if self.is_negative(message):
            return {
                "intent": pending_action.get("negative_intent") or "cancel_pending_action",
                "source": "pending_action",
                "pending_action": pending_action,
            }

        # clarify_exercise_count 状态下检测题目数量
        if pending_action.get("type") == "clarify_exercise_count" and self.has_question_count(message):
            return {
                "intent": "generate_exercise_document",
                "source": "pending_action",
                "pending_action": pending_action,
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                "payload": pending_action.get("payload") or {},
            }

        return None

    def resolve_from_last_assistant_message(self, message: str, context: dict) -> dict | None:
        """当 pending_action_json 为空时，回退分析上一条 assistant 消息的 metadata"""
        if not self.is_affirmative(message) and not self.is_negative(message):
            return None

        recent_messages = context.get("recent_messages") or []
        last_assistant = None
        for item in reversed(recent_messages):
            if item.get("role") == "assistant":
                last_assistant = item
                break

        if not last_assistant:
            return None

        metadata = last_assistant.get("metadata") or {}
        pending_action = metadata.get("derived_pending_action")
        if not pending_action:
            return None

        if self.is_affirmative(message):
            return {
                "intent": pending_action.get("confirm_intent"),
                "source": "last_assistant_message",
                "pending_action": pending_action,
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                "payload": pending_action.get("payload") or {},
            }

        return {
            "intent": pending_action.get("negative_intent") or "cancel_pending_action",
            "source": "last_assistant_message",
            "pending_action": pending_action,
        }

    def build_conversation_context_for_qa(self, recent_messages: list) -> list[dict]:
        """将最近消息转成适合传给千问的格式"""
        context = []
        for msg in recent_messages[-6:]:  # 最近6条
            if msg.role == "user":
                context.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                context.append({"role": "assistant", "content": msg.content})
        return context

    # ================================================================
    # update_after_response（文档 Section 16.2）
    # ================================================================

    def update_after_response(
        self,
        db,
        conversation,
        intent_result,      # IntentRouterResult
        tool_result: dict,
        response: dict,
    ) -> None:
        """
        根据 intent_result 和 tool_result 更新会话记忆。

        更新项：
        - last_topic
        - last_knowledge_point_ids
        - pending_action_json（来自 tool_result.pending_action_update 或清空）
        - context_summary_json（可选，暂存最近意图摘要）
        """
        from app.services.agent_conversation_service import agent_conversation_service

        pending_action_update = tool_result.get("pending_action_update") or {}
        response_pending_action_update = response.get("pending_action_update") or {}

        # 提取 topic
        topic = (
            intent_result.topic
            or pending_action_update.get("topic")
            or response_pending_action_update.get("topic")
        )

        # 提取 knowledge_point_ids
        knowledge_point_ids = (
            intent_result.knowledge_point_ids
            or response.get("related_knowledge_point_ids")
            or []
        )

        # 处理 pending_action
        if intent_result.tool_name == "cancel_pending_action":
            # 取消
            agent_conversation_service.update_memory(
                db=db,
                conversation=conversation,
                last_topic=topic,
                last_knowledge_point_ids=knowledge_point_ids,
                clear_pending=True,
            )
        else:
            if pending_action_update:
                agent_conversation_service.update_memory(
                    db=db,
                    conversation=conversation,
                    last_topic=topic,
                    last_knowledge_point_ids=knowledge_point_ids,
                    pending_action=pending_action_update,
                )
            else:
                agent_conversation_service.update_memory(
                    db=db,
                    conversation=conversation,
                    last_topic=topic,
                    last_knowledge_point_ids=knowledge_point_ids,
                    clear_pending=True,
                )

        # 更新上下文摘要（精简记录最近意图）
        summary = {
            "last_intent": intent_result.intent,
            "last_domain": intent_result.domain,
            "last_tool": intent_result.tool_name,
            "last_topic": topic,
        }
        conversation.context_summary_json = summary

    # ================================================================
    # 过期清理（文档 Section 16.3）
    # ================================================================

    def clear_expired_pending(self, db, conversation) -> bool:
        """
        检查并清理过期 pending_action。

        返回 True 表示已清理。
        """
        pending_action = conversation.pending_action_json
        if pending_action and self.is_pending_expired(pending_action):
            from app.services.agent_conversation_service import agent_conversation_service

            agent_conversation_service.update_memory(
                db=db,
                conversation=conversation,
                clear_pending=True,
            )
            return True
        return False


agent_memory_service = AgentMemoryService()
