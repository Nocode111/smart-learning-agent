"""
AgentOrchestrator 编排器 — 统一编排完整 Agent 流程。

文档参考：docs/LLM语义路由Agent最终架构_详细技术实现文档.md Section 12

流程：
  用户输入
    → ConversationService 读/建会话
    → MemoryService 构建上下文
    → RuleGate 高置信规则预判
    → LLMIntentRouter 语义意图识别
    → ToolExecutor 执行工具
    → ResponseComposer 生成最终回复
    → MemoryService 更新会话状态
    → 保存 agent_messages
    → 返回前端
"""

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.services.agent_conversation_service import agent_conversation_service
from app.services.agent_memory_service import agent_memory_service
from app.services.agent_reply_action_detector import agent_reply_action_detector
from app.services.agent_rule_gate_service import agent_rule_gate_service
from app.services.agent_tool_executor_service import agent_tool_executor_service
from app.services.agent_response_composer_service import agent_response_composer_service
from app.services.llm_intent_router_service import (
    IntentRouterResult,
    llm_intent_router_service,
)

logger = logging.getLogger(__name__)


class AgentOrchestratorService:
    """
    统一编排器。

    当前 agent_router_service.py 承担过多职责，Orchestrator 逐步接管核心流程，
    通过配置开关 enable_llm_intent_router 与旧路由并行运行。
    """

    def chat(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation_id: int | None = None,
        include_debug: bool = False,
    ) -> dict:
        """
        完整 Agent 流程（文档 Section 12.3）。

        参数：
            db: 数据库会话
            student_id: 当前用户 ID（来自 JWT）
            course_id: 课程 ID
            message: 用户当前输入
            conversation_id: 已有会话 ID（可选）
            include_debug: 是否在响应中附带 debug_intent
        """
        message = (message or "").strip()
        if settings.enable_agent_langgraph:
            from app.services.agent_graph_service import agent_graph_service

            return agent_graph_service.chat(
                db=db,
                student_id=student_id,
                course_id=course_id,
                message=message,
                conversation_id=conversation_id,
                include_debug=include_debug,
            )

        # ── 1. 获取或创建会话 ──
        conversation = agent_conversation_service.get_or_create_conversation(
            db=db,
            student_id=student_id,
            course_id=course_id,
            conversation_id=conversation_id,
            first_message=message,
        )

        # ── 2. 读取最近上下文 ──
        recent_messages = agent_conversation_service.get_recent_messages(
            db=db,
            conversation_id=conversation.id,
            limit=10,
        )
        context = agent_memory_service.build_context(conversation, recent_messages)

        # 2b. 补充 active_practice_session（文档 Section 16）
        from app.services.agent_practice_session_service import agent_practice_session_service
        active_practice_session = agent_practice_session_service.get_active_session(
            db=db,
            conversation_id=conversation.id,
            student_id=student_id,
            course_id=course_id,
        )
        if active_practice_session:
            context["active_practice_session"] = {
                "session_id": active_practice_session.id,
                "topic": active_practice_session.topic,
                "status": active_practice_session.status,
                "question_count": active_practice_session.question_count,
                "answered_count": active_practice_session.answered_count,
                "current_question_no": active_practice_session.current_question_no,
            }

        # 2c. 加载当前会话附件（文档 Section 13.1）
        from app.services.agent_attachment_service import agent_attachment_service
        attachments = agent_attachment_service.list_active_attachments(
            db=db,
            conversation_id=conversation.id,
            student_id=student_id,
            course_id=course_id,
        )
        context["attachments"] = [
            agent_attachment_service.serialize_for_context(a)
            for a in attachments[-10:]  # 最多传最近10个给意图识别
        ]
        context["conversation"] = conversation
        context["conversation_id"] = conversation.id
        context["course_id"] = course_id
        context["student_id"] = student_id
        context = self._attach_long_term_memory_context(
            db=db,
            context=context,
            student_id=student_id,
            course_id=course_id,
            message=message,
        )

        # ── 3. 保存用户消息 ──
        user_message = agent_conversation_service.add_message(
            db=db,
            conversation=conversation,
            role="user",
            content=message,
            message_type="text",
        )

        # ── 4. 意图识别 ──
        intent_result = self._resolve_intent(
            db=db,
            message=message,
            student_id=student_id,
            course_id=course_id,
            context=context,
        )

        # ── 5. 执行工具 ──
        tool_result = agent_tool_executor_service.execute(
            db=db,
            intent_result=intent_result,
            conversation=conversation,
            user_message=message,
            student_id=student_id,
            course_id=course_id,
            context=context,
        )

        # ── 6. 组装响应 ──
        response = agent_response_composer_service.compose(
            intent_result=intent_result,
            tool_result=tool_result,
            conversation_id=conversation.id,
            include_debug=include_debug,
        )

        # ── 7. 更新会话记忆 ──
        agent_memory_service.update_after_response(
            db=db,
            conversation=conversation,
            intent_result=intent_result,
            tool_result=tool_result,
            response=response,
        )

        # ── 8. 后处理：分析 assistant 回复，自动生成 derived_pending_action ──
        derived_pending_action = None
        if not response.get("skip_reply_action_detection"):
            derived_pending_action = agent_reply_action_detector.detect(
                assistant_text=response.get("text") or "",
                last_topic=conversation.last_topic,
                knowledge_point_ids=response.get("related_knowledge_point_ids")
                or conversation.last_knowledge_point_ids
                or [],
            )
            if derived_pending_action:
                agent_conversation_service.update_memory(
                    db=db,
                    conversation=conversation,
                    last_topic=derived_pending_action.get("topic"),
                    last_knowledge_point_ids=derived_pending_action.get("knowledge_point_ids") or [],
                    pending_action=derived_pending_action,
                )

        memory_write_result = self._write_long_term_memory(
            db=db,
            student_id=student_id,
            course_id=course_id,
            user_message=message,
            intent_result=intent_result,
            tool_result=tool_result,
            response=response,
            context=context,
            conversation_id=conversation.id,
            source_message_id=user_message.id,
        )

        # ── 9. 保存 AI 消息 ──
        agent_conversation_service.add_message(
            db=db,
            conversation=conversation,
            role="assistant",
            content=response.get("text"),
            message_type=response.get("type", "answer"),
            intent=response.get("intent"),
            qa_id=response.get("qa_id"),
            document_id=response.get("document", {}).get("id") if response.get("document") else None,
            related_knowledge_point_ids=response.get("related_knowledge_point_ids"),
            agent_steps=response.get("agent_steps"),
            retrieved_chunks=response.get("retrieved_chunks"),
            metadata={
                "document": response.get("document"),
                "practice_session": response.get("practice_session"),
                "practice_result": response.get("practice_result"),
                "intent_result": intent_result.model_dump(),
                "tool_result": {
                    "type": tool_result.get("type"),
                    "text": (tool_result.get("text") or "")[:200],
                },
                "derived_pending_action": derived_pending_action,
                "learning_goal": response.get("learning_goal"),
                "goal_plan": response.get("goal_plan"),
                "goal_loop": response.get("goal_loop"),
                "memory_write_result": memory_write_result,
            },
        )

        # ── 10. 提交 ──
        db.commit()

        return response

    # ================================================================
    # 意图解析（RuleGate → LLM，文档 Section 11.4）
    # ================================================================

    def _resolve_intent(
        self,
        db: Session,
        message: str,
        student_id: int,
        course_id: int,
        context: dict,
    ) -> IntentRouterResult:
        """
        意图解析流程：
        1. 先走 RuleGate 高置信预判
        2. 未命中则走 LLMIntentRouter
        3. LLM 失败则走 RuleGate fallback
        """
        # ── RuleGate 高置信预判 ──
        rule_result = agent_rule_gate_service.try_resolve(message, context)
        if rule_result:
            logger.info("RuleGate 命中: %s", rule_result.get("reason"))
            return IntentRouterResult.from_rule(rule_result)

        # ── LLM 语义路由 ──
        try:
            intent_result = llm_intent_router_service.route(
                db=db,
                message=message,
                course_id=course_id,
                student_id=student_id,
                context=context,
            )
            logger.info(
                "LLM 路由完成: domain=%s intent=%s tool=%s confidence=%.2f",
                intent_result.domain,
                intent_result.intent,
                intent_result.tool_name,
                intent_result.confidence,
            )
            return intent_result

        except Exception as exc:
            logger.exception("LLM 路由异常，使用 RuleGate fallback")
            fallback = agent_rule_gate_service.fallback_resolve(message, context)
            return IntentRouterResult.from_rule(fallback)

    def _attach_long_term_memory_context(
        self,
        db: Session,
        context: dict,
        student_id: int,
        course_id: int,
        message: str,
    ) -> dict:
        from app.services.agent_long_term_memory_service import agent_long_term_memory_service
        from app.services.agent_profile_memory_bridge_service import agent_profile_memory_bridge_service
        from app.services.agent_graphiti_memory_service import agent_graphiti_memory_service

        try:
            memory_context = agent_long_term_memory_service.build_memory_context(
                db=db,
                student_id=student_id,
                course_id=course_id,
                message=message,
                per_type_limit=5,
            )
        except Exception:
            logger.exception("长期记忆检索失败，使用空记忆上下文")
            memory_context = {
                "profile_memories": [],
                "preference_memories": [],
                "learning_state_memories": [],
                "episodic_memories": [],
                "semantic_memories": [],
                "procedural_memories": [],
                "memory_context_text": "",
            }

        enriched = dict(context)
        try:
            profile_memory_context = agent_profile_memory_bridge_service.build_context(
                db=db,
                student_id=student_id,
                course_id=course_id,
                memory_context=memory_context,
            )
        except Exception:
            logger.exception("学习画像与长期记忆桥接失败，继续使用长期记忆上下文")
            profile_memory_context = {
                "learning_profile": {},
                "learning_profile_with_memory": {},
                "learning_profile_memory_context_text": "",
            }
        enriched["long_term_memory"] = memory_context
        enriched["learning_profile"] = profile_memory_context.get("learning_profile") or {}
        enriched["learning_profile_with_memory"] = profile_memory_context.get("learning_profile_with_memory") or {}
        enriched["learning_profile_memory_context_text"] = profile_memory_context.get("learning_profile_memory_context_text") or ""
        enriched["memory_context_text"] = memory_context.get("memory_context_text") or ""
        graphiti_context = agent_graphiti_memory_service.search_sync(
            student_id=student_id,
            course_id=course_id,
            query=message,
        )
        enriched["graphiti_memory"] = graphiti_context
        if graphiti_context.get("context_text"):
            enriched["memory_context_text"] = "\n\n".join(
                item for item in [enriched["memory_context_text"], graphiti_context["context_text"]] if item
            )
        return enriched

    def _write_long_term_memory(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result: IntentRouterResult,
        tool_result: dict,
        response: dict,
        context: dict,
        conversation_id: int | None,
        source_message_id: int | None,
    ) -> dict:
        if not settings.enable_agent_memory_auto_extract:
            return {"enabled": False, "reason": "ENABLE_AGENT_MEMORY_AUTO_EXTRACT=false"}

        from app.services.agent_memory_extraction_service import agent_memory_extraction_service

        try:
            result = agent_memory_extraction_service.extract_and_persist(
                db=db,
                student_id=student_id,
                course_id=course_id,
                user_message=user_message,
                intent_result=intent_result,
                tool_result=tool_result,
                response=response,
                context=context,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
            )
            self._sync_memories_to_graphiti(db, student_id, result)
            return result
        except Exception as exc:
            logger.exception("长期记忆自动写入失败，继续返回本轮回答")
            return {"enabled": True, "error": str(exc), "written_count": 0}

    @staticmethod
    def _sync_memories_to_graphiti(db: Session, student_id: int, memory_write_result: dict) -> None:
        memory_ids = memory_write_result.get("memory_ids") or []
        if not memory_ids:
            return
        from app.models.agent_memory import AgentMemory
        from app.services.agent_graphiti_memory_service import agent_graphiti_memory_service

        for memory_id in memory_ids:
            memory = db.query(AgentMemory).filter(
                AgentMemory.id == memory_id,
                AgentMemory.student_id == student_id,
            ).first()
            if memory:
                agent_graphiti_memory_service.add_memory_episode_sync(
                    student_id=student_id,
                    course_id=memory.course_id,
                    memory=memory,
                    reference_time=memory.updated_at,
                )


# ── 单例 ──────────────────────────────────────────────────────

agent_orchestrator_service = AgentOrchestratorService()
