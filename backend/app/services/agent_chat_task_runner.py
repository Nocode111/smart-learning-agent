"""
异步任务运行器 — 使用 emit 回调实现实时 SSE 事件推送，支持 LLM token 流式生成。

文档参考：docs/智能答疑真实流式回答SSE方案_详细技术实现文档.md Section 7, 11
"""

import asyncio
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.agent_chat_task import AgentChatTask
from app.services.agent_chat_task_service import AgentTaskCanceled, agent_chat_task_service

logger = logging.getLogger(__name__)


class AgentChatTaskRunner:
    """异步任务运行器 — 实时 SSE 事件推送 + 可取消"""

    # ── 取消检查 ──────────────────────────────────────────

    async def check_cancel(self, db: Session, task: AgentChatTask):
        """检查取消状态，被取消则抛出 AgentTaskCanceled（文档 Section 7.3/14.2）"""
        db.commit()
        db.expire(task)
        db.refresh(task)
        if task.cancel_requested or task.status in ("cancel_requested", "canceled"):
            raise AgentTaskCanceled()

    # ── 事件发送辅助 ──────────────────────────────────────

    async def emit_stage(self, emit, db: Session, task: AgentChatTask, stage: str, text: str):
        """发送阶段事件并写入数据库（文档 Section 7.2）"""
        agent_chat_task_service.mark_stage(db, task, stage, text)
        await emit("stage", {
            "stage": stage,
            "text": text,
        })

    # ── 主入口（文档 Section 7.3） ──────────────────────────

    async def run_task(self, task_uuid: str, emit):
        """
        运行任务主流程，通过 emit 回调实时推送 SSE 事件。

        不再返回事件列表，所有事件在产生时立即通过 emit 推送。
        """
        if settings.enable_agent_langgraph:
            from app.services.agent_graph_service import agent_graph_service

            await agent_graph_service.run_task(
                task_uuid=task_uuid,
                emit=emit,
                check_cancel=self.check_cancel,
            )
            return

        db = SessionLocal()
        task = None

        try:
            task = agent_chat_task_service.get_task(db, task_uuid)
            if not task:
                await emit("task_failed", {"error": "任务不存在"})
                return

            # 阶段 1：标记运行
            agent_chat_task_service.mark_running(db, task, stage="building_context")
            await emit("task_started", {
                "task_uuid": task_uuid,
                "assistant_message_id": task.assistant_message_id,
            })

            await self.check_cancel(db, task)

            # 阶段 2：构建上下文
            await self.emit_stage(emit, db, task, "building_context", "正在构建上下文")
            context = await self._build_context(db, task)
            await self.check_cancel(db, task)

            # 阶段 3：意图识别
            await self.emit_stage(emit, db, task, "intent_routing", "正在分析问题意图")
            intent_result = await self._route_intent(db, task, context)
            await self.check_cancel(db, task)

            # 阶段 4：执行工具（流式）
            await self.emit_stage(emit, db, task, "executing_tool", "正在执行对应学习工具")
            await self.check_cancel(db, task)

            response, derived_pending_action, tool_result = await self._execute_tool_streaming_if_possible(
                db=db,
                task=task,
                intent_result=intent_result,
                context=context,
                emit=emit,
            )

            await self.check_cancel(db, task)

            # 阶段 5：保存结果
            agent_chat_task_service.mark_stage(db, task, "saving", "正在保存结果")

            result = {
                "answer": response.get("text") or "",
                "type": response.get("type", "answer"),
                "intent": response.get("intent"),
                "qa_id": response.get("qa_id"),
                "document": response.get("document"),
                "document_id": response.get("document", {}).get("id") if response.get("document") else None,
                "agent_steps": response.get("agent_steps") or [],
                "retrieved_chunks": response.get("retrieved_chunks") or [],
                "related_knowledge_point_ids": response.get("related_knowledge_point_ids") or [],
                "local_file_operation": response.get("local_file_operation"),
                "metadata": {
                    "document": response.get("document"),
                    "practice_session": response.get("practice_session"),
                    "practice_result": response.get("practice_result"),
                    "attachments": response.get("attachments") or [],
                    "intent_result": intent_result.model_dump(),
                    "tool_result": {
                        "type": tool_result.get("type"),
                        "text": (tool_result.get("text") or "")[:200],
                    },
                    "derived_pending_action": derived_pending_action,
                    "local_file_operation": response.get("local_file_operation"),
                    "goal_loop": response.get("goal_loop"),
                },
            }

            # 保存前最后检查取消（文档 Section 20.4）
            await self.check_cancel(db, task)
            agent_chat_task_service.mark_completed(db, task, result)

            await emit("task_completed", {
                "status": "completed",
                "message": {
                    "id": task.assistant_message_id,
                    "role": "assistant",
                    "content": response.get("text") or "",
                    "message_type": response.get("type", "answer"),
                    "status": "completed",
                    "intent": response.get("intent"),
                    "qa_id": response.get("qa_id"),
                    "document": response.get("document"),
                    "agent_steps": response.get("agent_steps") or [],
                    "retrieved_chunks": response.get("retrieved_chunks") or [],
                    "practice_session": response.get("practice_session"),
                    "practice_result": response.get("practice_result"),
                    "attachments": response.get("attachments") or [],
                    "local_file_operation": response.get("local_file_operation"),
                    "goal_loop": response.get("goal_loop"),
                },
            })

            db.commit()

        except AgentTaskCanceled:
            if task:
                agent_chat_task_service.mark_canceled(db, task)
                db.commit()
            await emit("task_canceled", {
                "status": "canceled",
                "text": "本次提问已停止。",
            })

        except Exception as exc:
            logger.exception("任务执行失败: %s", task_uuid)
            if task:
                db.commit()
                db.refresh(task)
                if task.cancel_requested or task.status in ("cancel_requested", "canceled"):
                    agent_chat_task_service.mark_canceled(db, task)
                    db.commit()
                    await emit("task_canceled", {
                        "status": "canceled",
                        "text": "本次提问已停止。",
                    })
                else:
                    agent_chat_task_service.mark_failed(db, task, str(exc))
                    db.commit()
            await emit("task_failed", {"error": str(exc)})

        finally:
            db.close()

    # ── 上下文构建 ──────────────────────────────────────

    async def _build_context(self, db: Session, task: AgentChatTask) -> dict:
        """构建 Agent 上下文（复用 orchestrator 逻辑）"""
        from app.services.agent_conversation_service import agent_conversation_service
        from app.services.agent_attachment_service import agent_attachment_service
        from app.services.agent_memory_service import agent_memory_service
        from app.services.agent_practice_session_service import agent_practice_session_service

        conversation = agent_conversation_service.get_conversation_by_id(
            db=db,
            student_id=task.student_id,
            conversation_id=task.conversation_id,
        )
        recent_messages = agent_conversation_service.get_recent_messages(
            db=db,
            conversation_id=task.conversation_id,
            limit=10,
        )
        recent_messages = [
            msg for msg in recent_messages
            if msg.id not in {task.user_message_id, task.assistant_message_id}
        ]

        attachments = agent_attachment_service.list_active_attachments(
            db=db,
            conversation_id=task.conversation_id,
            student_id=task.student_id,
            course_id=task.course_id,
        )

        context = agent_memory_service.build_context(conversation, recent_messages)

        active_practice_session = agent_practice_session_service.get_active_session(
            db=db,
            conversation_id=task.conversation_id,
            student_id=task.student_id,
            course_id=task.course_id,
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

        context["conversation"] = conversation
        context["conversation_id"] = task.conversation_id
        context["attachments"] = [
            agent_attachment_service.serialize_for_context(a)
            for a in attachments[-10:]
        ]
        context["course_id"] = task.course_id
        context["student_id"] = task.student_id
        context = self._attach_long_term_memory_context(
            db=db,
            context=context,
            student_id=task.student_id,
            course_id=task.course_id,
            message=task.request_message,
        )
        return context

    # ── 意图识别 ──────────────────────────────────────

    async def _route_intent(self, db: Session, task: AgentChatTask, context: dict) -> dict:
        """意图识别（复用 LLM Intent Router）"""
        from app.services.llm_intent_router_service import llm_intent_router_service
        from app.services.agent_rule_gate_service import agent_rule_gate_service
        from app.services.llm_intent_router_service import IntentRouterResult

        rule_result = agent_rule_gate_service.try_resolve(task.request_message, context)
        if rule_result:
            return IntentRouterResult.from_rule(rule_result)

        try:
            return llm_intent_router_service.route(
                db=db,
                message=task.request_message,
                course_id=task.course_id,
                student_id=task.student_id,
                context=context,
            )
        except Exception:
            fallback = agent_rule_gate_service.fallback_resolve(task.request_message, context)
            return IntentRouterResult.from_rule(fallback)

    # ── 流式工具执行（文档 Section 11） ─────────────────

    async def _execute_tool_streaming_if_possible(
        self,
        db: Session,
        task: AgentChatTask,
        intent_result,
        context: dict,
        emit,
    ) -> tuple[dict, dict | None, dict]:
        """
        执行工具，对支持流式的工具走 token 流式，其他走 tool_result。

        返回：(response, derived_pending_action, tool_result)
        """
        from app.services.agent_tool_executor_service import agent_tool_executor_service
        from app.services.agent_response_composer_service import agent_response_composer_service
        from app.services.agent_memory_service import agent_memory_service
        from app.services.agent_reply_action_detector import agent_reply_action_detector
        from app.services.agent_conversation_service import agent_conversation_service

        conversation = context.get("conversation")

        # 尝试流式执行
        tool_result = await agent_tool_executor_service.execute_streaming(
            db=db,
            intent_result=intent_result,
            conversation=conversation,
            user_message=task.request_message,
            student_id=task.student_id,
            course_id=task.course_id,
            context=context,
            emit=emit,
            check_cancel=self.check_cancel,
            task=task,
        )

        response = agent_response_composer_service.compose(
            intent_result=intent_result,
            tool_result=tool_result,
            conversation_id=task.conversation_id,
            include_debug=False,
        )

        agent_memory_service.update_after_response(
            db=db,
            conversation=conversation,
            intent_result=intent_result,
            tool_result=tool_result,
            response=response,
        )

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

        self._write_long_term_memory(
            db=db,
            task=task,
            user_message=task.request_message,
            intent_result=intent_result,
            tool_result=tool_result,
            response=response,
            context=context,
        )

        return response, derived_pending_action, tool_result

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
        task: AgentChatTask,
        user_message: str,
        intent_result,
        tool_result: dict,
        response: dict,
        context: dict,
    ) -> dict:
        if not settings.enable_agent_memory_auto_extract:
            return {"enabled": False, "reason": "ENABLE_AGENT_MEMORY_AUTO_EXTRACT=false"}

        from app.services.agent_memory_extraction_service import agent_memory_extraction_service

        try:
            result = agent_memory_extraction_service.extract_and_persist(
                db=db,
                student_id=task.student_id,
                course_id=task.course_id,
                user_message=user_message,
                intent_result=intent_result,
                tool_result=tool_result,
                response=response,
                context=context,
                conversation_id=task.conversation_id,
                source_message_id=task.user_message_id,
                source_task_id=task.id,
            )
            self._sync_memories_to_graphiti(db, task.student_id, result)
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

    # ── 检索 ──────────────────────────────────────────

    async def _retrieve(self, db: Session, task: AgentChatTask, intent_result: dict) -> dict:
        """执行检索（复用 _qa_answer 的检索逻辑）"""
        from app.services.rag_service import rag_service

        attachment_ids = intent_result.get("target_attachment_ids") or []
        retrieval_scope = intent_result.get("retrieval_scope") or "hybrid"

        attachment_chunks = []
        course_chunks = []

        if retrieval_scope in ("attachments_only", "attachments_first", "hybrid"):
            if attachment_ids:
                attachment_chunks = rag_service.retrieve_by_attachment_ids(
                    query=task.request_message,
                    attachment_ids=attachment_ids,
                    conversation_id=task.conversation_id,
                    student_id=task.student_id,
                    course_id=task.course_id,
                    db=db,
                )
            elif retrieval_scope != "course_only":
                attachment_chunks = rag_service.retrieve_attachments(
                    query=task.request_message,
                    conversation_id=task.conversation_id,
                    student_id=task.student_id,
                    course_id=task.course_id,
                    db=db,
                )

        if retrieval_scope in ("course_only", "attachments_first", "hybrid"):
            course_chunks = rag_service.retrieve(task.request_message, task.course_id)

        return {
            "attachment_chunks": attachment_chunks,
            "course_chunks": course_chunks,
            "retrieval_scope": retrieval_scope,
        }

    # ── 流式生成（文档 Section 8-9） ────────────────────

    async def _stream_generate(
        self,
        db: Session,
        task: AgentChatTask,
        intent_result: dict,
        retrieval_result: dict,
        context: dict,
    ):
        """流式 LLM 生成，每个 token 后检查取消（文档 Section 9.2）"""
        from app.services.qwen_client import async_qwen_client
        from app.services.qa_agent_service import get_qa_agent_service
        from app.prompts.qa_prompt import build_qa_prompt

        qa_service = get_qa_agent_service()

        profile = qa_service.profile_service.get_profile_for_agent(
            db, task.student_id, task.course_id
        )

        chunks = retrieval_result.get("attachment_chunks", []) + retrieval_result.get("course_chunks", [])
        conversation_context = [
            {"role": item.get("role"), "content": item.get("content") or ""}
            for item in (context.get("recent_messages") or [])[-6:]
            if item.get("content")
        ]
        messages = build_qa_prompt(profile, chunks, task.request_message, conversation_context)

        try:
            async for token in async_qwen_client.stream_chat(messages):
                yield token
        except Exception:
            from app.services.qwen_client import qwen_client
            answer = qwen_client.chat(messages)
            chunk_size = 10
            for i in range(0, len(answer), chunk_size):
                yield answer[i:i + chunk_size]
                await asyncio.sleep(0.01)


agent_chat_task_runner = AgentChatTaskRunner()
