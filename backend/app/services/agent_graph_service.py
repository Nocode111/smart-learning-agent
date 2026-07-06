"""
LangGraph 编排服务。

第二阶段目标：先把现有 Agent 主流程节点化，保持前端接口和业务行为不变。
长期记忆、Graphiti 图谱记忆会在后续阶段接入 retrieve_memory / write_memory 节点。
"""

import logging
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.agent_chat_task import AgentChatTask
from app.services.agent_chat_task_service import AgentTaskCanceled, agent_chat_task_service
from app.services.agent_conversation_service import agent_conversation_service
from app.services.agent_memory_service import agent_memory_service
from app.services.agent_response_composer_service import agent_response_composer_service
from app.services.agent_tool_executor_service import agent_tool_executor_service
from app.services.llm_intent_router_service import IntentRouterResult

logger = logging.getLogger(__name__)


class AgentGraphState(TypedDict, total=False):
    db: Session
    student_id: int
    course_id: int
    message: str
    conversation_id: int | None
    include_debug: bool

    task_uuid: str
    task: AgentChatTask
    emit: Any
    check_cancel: Any

    conversation: Any
    recent_messages: list
    context: dict
    intent_result: IntentRouterResult
    tool_result: dict
    response: dict
    derived_pending_action: dict | None
    user_message_id: int | None
    memory_write_result: dict | None


class AgentGraphService:
    """将现有 Agent 流程包装为 LangGraph 状态图。"""

    def __init__(self):
        self._sync_graph = None
        self._task_graph = None

    # ================================================================
    # 公开入口：同步 chat
    # ================================================================

    def chat(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation_id: int | None = None,
        include_debug: bool = False,
    ) -> dict:
        graph = self._get_sync_graph()
        final_state = graph.invoke(
            {
                "db": db,
                "student_id": student_id,
                "course_id": course_id,
                "message": (message or "").strip(),
                "conversation_id": conversation_id,
                "include_debug": include_debug,
            }
        )
        return final_state["response"]

    # ================================================================
    # 公开入口：流式任务
    # ================================================================

    async def run_task(self, task_uuid: str, emit, check_cancel) -> None:
        db = SessionLocal()
        task = None

        try:
            task = agent_chat_task_service.get_task(db, task_uuid)
            if not task:
                await emit("task_failed", {"error": "任务不存在"})
                return

            agent_chat_task_service.mark_running(db, task, stage="building_context")
            await emit(
                "task_started",
                {
                    "task_uuid": task_uuid,
                    "assistant_message_id": task.assistant_message_id,
                },
            )

            await check_cancel(db, task)

            graph = self._get_task_graph()
            await graph.ainvoke(
                {
                    "db": db,
                    "task_uuid": task_uuid,
                    "task": task,
                    "emit": emit,
                    "check_cancel": check_cancel,
                    "student_id": task.student_id,
                    "course_id": task.course_id,
                    "conversation_id": task.conversation_id,
                    "message": task.request_message,
                }
            )

        except AgentTaskCanceled:
            if task:
                agent_chat_task_service.mark_canceled(db, task)
                db.commit()
            await emit(
                "task_canceled",
                {
                    "status": "canceled",
                    "text": "本次提问已停止。",
                },
            )

        except Exception as exc:
            logger.exception("LangGraph 任务执行失败: %s", task_uuid)
            if task:
                db.commit()
                db.refresh(task)
                if task.cancel_requested or task.status in ("cancel_requested", "canceled"):
                    agent_chat_task_service.mark_canceled(db, task)
                    db.commit()
                    await emit(
                        "task_canceled",
                        {
                            "status": "canceled",
                            "text": "本次提问已停止。",
                        },
                    )
                else:
                    agent_chat_task_service.mark_failed(db, task, str(exc))
                    db.commit()
                    await emit("task_failed", {"error": str(exc)})
            else:
                await emit("task_failed", {"error": str(exc)})

        finally:
            db.close()

    # ================================================================
    # Graph 构建
    # ================================================================

    def _get_sync_graph(self):
        if self._sync_graph is None:
            self._sync_graph = self._build_sync_graph()
        return self._sync_graph

    def _get_task_graph(self):
        if self._task_graph is None:
            self._task_graph = self._build_task_graph()
        return self._task_graph

    def _build_sync_graph(self):
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(AgentGraphState)
        graph.add_node("load_conversation", self._sync_load_conversation)
        graph.add_node("load_context", self._sync_load_context)
        graph.add_node("retrieve_memory", self._sync_retrieve_memory)
        graph.add_node("persist_user_message", self._sync_persist_user_message)
        graph.add_node("route_intent", self._sync_route_intent)
        graph.add_node("execute_tool", self._sync_execute_tool)
        graph.add_node("compose_response", self._sync_compose_response)
        graph.add_node("update_state", self._sync_update_state)
        graph.add_node("detect_reply_action", self._sync_detect_reply_action)
        graph.add_node("write_memory", self._sync_write_memory)
        graph.add_node("persist_result", self._sync_persist_result)

        graph.add_edge(START, "load_conversation")
        graph.add_edge("load_conversation", "load_context")
        graph.add_edge("load_context", "retrieve_memory")
        graph.add_edge("retrieve_memory", "persist_user_message")
        graph.add_edge("persist_user_message", "route_intent")
        graph.add_edge("route_intent", "execute_tool")
        graph.add_edge("execute_tool", "compose_response")
        graph.add_edge("compose_response", "update_state")
        graph.add_edge("update_state", "detect_reply_action")
        graph.add_edge("detect_reply_action", "write_memory")
        graph.add_edge("write_memory", "persist_result")
        graph.add_edge("persist_result", END)
        return graph.compile()

    def _build_task_graph(self):
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(AgentGraphState)
        graph.add_node("load_context", self._task_load_context)
        graph.add_node("retrieve_memory", self._task_retrieve_memory)
        graph.add_node("route_intent", self._task_route_intent)
        graph.add_node("execute_tool", self._task_execute_tool)
        graph.add_node("write_memory", self._task_write_memory)
        graph.add_node("persist_result", self._task_persist_result)

        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "retrieve_memory")
        graph.add_edge("retrieve_memory", "route_intent")
        graph.add_edge("route_intent", "execute_tool")
        graph.add_edge("execute_tool", "write_memory")
        graph.add_edge("write_memory", "persist_result")
        graph.add_edge("persist_result", END)
        return graph.compile()

    # ================================================================
    # 同步图节点
    # ================================================================

    def _sync_load_conversation(self, state: AgentGraphState) -> dict:
        conversation = agent_conversation_service.get_or_create_conversation(
            db=state["db"],
            student_id=state["student_id"],
            course_id=state["course_id"],
            conversation_id=state.get("conversation_id"),
            first_message=state["message"],
        )
        return {"conversation": conversation, "conversation_id": conversation.id}

    def _sync_load_context(self, state: AgentGraphState) -> dict:
        conversation = state["conversation"]
        recent_messages = agent_conversation_service.get_recent_messages(
            db=state["db"],
            conversation_id=conversation.id,
            limit=10,
        )
        context = self._build_runtime_context(
            db=state["db"],
            conversation=conversation,
            recent_messages=recent_messages,
            student_id=state["student_id"],
            course_id=state["course_id"],
        )
        return {"recent_messages": recent_messages, "context": context}

    def _sync_persist_user_message(self, state: AgentGraphState) -> dict:
        user_message = agent_conversation_service.add_message(
            db=state["db"],
            conversation=state["conversation"],
            role="user",
            content=state["message"],
            message_type="text",
        )
        return {"user_message_id": user_message.id}

    def _sync_retrieve_memory(self, state: AgentGraphState) -> dict:
        context = self._attach_long_term_memory_context(
            db=state["db"],
            context=state["context"],
            student_id=state["student_id"],
            course_id=state["course_id"],
            message=state["message"],
        )
        return {"context": context}

    def _sync_route_intent(self, state: AgentGraphState) -> dict:
        return {
            "intent_result": self._route_intent(
                db=state["db"],
                message=state["message"],
                student_id=state["student_id"],
                course_id=state["course_id"],
                context=state["context"],
            )
        }

    def _sync_execute_tool(self, state: AgentGraphState) -> dict:
        tool_result = agent_tool_executor_service.execute(
            db=state["db"],
            intent_result=state["intent_result"],
            conversation=state["conversation"],
            user_message=state["message"],
            student_id=state["student_id"],
            course_id=state["course_id"],
            context=state["context"],
        )
        return {"tool_result": tool_result}

    def _sync_compose_response(self, state: AgentGraphState) -> dict:
        response = agent_response_composer_service.compose(
            intent_result=state["intent_result"],
            tool_result=state["tool_result"],
            conversation_id=state["conversation"].id,
            include_debug=state.get("include_debug", False),
        )
        return {"response": response}

    def _sync_update_state(self, state: AgentGraphState) -> dict:
        agent_memory_service.update_after_response(
            db=state["db"],
            conversation=state["conversation"],
            intent_result=state["intent_result"],
            tool_result=state["tool_result"],
            response=state["response"],
        )
        return {}

    def _sync_detect_reply_action(self, state: AgentGraphState) -> dict:
        derived_pending_action = self._detect_and_update_reply_action(
            db=state["db"],
            conversation=state["conversation"],
            response=state["response"],
        )
        return {"derived_pending_action": derived_pending_action}

    def _sync_write_memory(self, state: AgentGraphState) -> dict:
        result = self._write_long_term_memory(
            db=state["db"],
            student_id=state["student_id"],
            course_id=state["course_id"],
            user_message=state["message"],
            intent_result=state["intent_result"],
            tool_result=state["tool_result"],
            response=state["response"],
            context=state["context"],
            conversation_id=state["conversation"].id,
            source_message_id=state.get("user_message_id"),
            source_task_id=None,
        )
        return {"memory_write_result": result}

    def _sync_persist_result(self, state: AgentGraphState) -> dict:
        response = state["response"]
        agent_conversation_service.add_message(
            db=state["db"],
            conversation=state["conversation"],
            role="assistant",
            content=response.get("text"),
            message_type=response.get("type", "answer"),
            intent=response.get("intent"),
            qa_id=response.get("qa_id"),
            document_id=response.get("document", {}).get("id") if response.get("document") else None,
            related_knowledge_point_ids=response.get("related_knowledge_point_ids"),
            agent_steps=response.get("agent_steps"),
            retrieved_chunks=response.get("retrieved_chunks"),
            metadata=self._build_assistant_metadata(
                response=response,
                intent_result=state["intent_result"],
                tool_result=state["tool_result"],
                derived_pending_action=state.get("derived_pending_action"),
                memory_write_result=state.get("memory_write_result"),
            ),
        )
        state["db"].commit()
        return {}

    # ================================================================
    # 流式任务图节点
    # ================================================================

    async def _task_load_context(self, state: AgentGraphState) -> dict:
        await self._emit_stage(state, "building_context", "正在构建上下文")
        task = state["task"]
        db = state["db"]
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
            msg
            for msg in recent_messages
            if msg.id not in {task.user_message_id, task.assistant_message_id}
        ]
        context = self._build_runtime_context(
            db=db,
            conversation=conversation,
            recent_messages=recent_messages,
            student_id=task.student_id,
            course_id=task.course_id,
        )
        await self._check_cancel(state)
        return {
            "conversation": conversation,
            "conversation_id": task.conversation_id,
            "recent_messages": recent_messages,
            "context": context,
        }

    async def _task_retrieve_memory(self, state: AgentGraphState) -> dict:
        context = await self._attach_long_term_memory_context_async(
            db=state["db"],
            context=state["context"],
            student_id=state["task"].student_id,
            course_id=state["task"].course_id,
            message=state["task"].request_message,
        )
        await self._check_cancel(state)
        return {"context": context}

    async def _task_route_intent(self, state: AgentGraphState) -> dict:
        await self._emit_stage(state, "intent_routing", "正在分析问题意图")
        intent_result = self._route_intent(
            db=state["db"],
            message=state["task"].request_message,
            student_id=state["task"].student_id,
            course_id=state["task"].course_id,
            context=state["context"],
        )
        await self._check_cancel(state)
        return {"intent_result": intent_result}

    async def _task_execute_tool(self, state: AgentGraphState) -> dict:
        await self._emit_stage(state, "executing_tool", "正在执行对应学习工具")
        await self._check_cancel(state)

        task = state["task"]
        tool_result = await agent_tool_executor_service.execute_streaming(
            db=state["db"],
            intent_result=state["intent_result"],
            conversation=state["conversation"],
            user_message=task.request_message,
            student_id=task.student_id,
            course_id=task.course_id,
            context=state["context"],
            emit=state["emit"],
            check_cancel=state["check_cancel"],
            task=task,
        )
        response = agent_response_composer_service.compose(
            intent_result=state["intent_result"],
            tool_result=tool_result,
            conversation_id=task.conversation_id,
            include_debug=False,
        )
        agent_memory_service.update_after_response(
            db=state["db"],
            conversation=state["conversation"],
            intent_result=state["intent_result"],
            tool_result=tool_result,
            response=response,
        )
        derived_pending_action = self._detect_and_update_reply_action(
            db=state["db"],
            conversation=state["conversation"],
            response=response,
        )
        await self._check_cancel(state)
        return {
            "tool_result": tool_result,
            "response": response,
            "derived_pending_action": derived_pending_action,
        }

    async def _task_write_memory(self, state: AgentGraphState) -> dict:
        await self._emit_stage(state, "writing_memory", "正在整理长期记忆")
        task = state["task"]
        result = await self._write_long_term_memory_async(
            db=state["db"],
            student_id=task.student_id,
            course_id=task.course_id,
            user_message=task.request_message,
            intent_result=state["intent_result"],
            tool_result=state["tool_result"],
            response=state["response"],
            context=state["context"],
            conversation_id=task.conversation_id,
            source_message_id=task.user_message_id,
            source_task_id=task.id,
        )
        await self._check_cancel(state)
        return {"memory_write_result": result}

    async def _task_persist_result(self, state: AgentGraphState) -> dict:
        task = state["task"]
        response = state["response"]
        tool_result = state["tool_result"]

        agent_chat_task_service.mark_stage(state["db"], task, "saving", "正在保存结果")
        result = self._build_task_result(
            response=response,
            intent_result=state["intent_result"],
            tool_result=tool_result,
            derived_pending_action=state.get("derived_pending_action"),
        )
        await self._check_cancel(state)
        agent_chat_task_service.mark_completed(state["db"], task, result)

        await state["emit"](
            "task_completed",
            {
                "status": "completed",
                "message": self._build_task_completed_message(task, response),
            },
        )
        state["db"].commit()
        return {}

    # ================================================================
    # 共享辅助逻辑
    # ================================================================

    def _build_runtime_context(
        self,
        db: Session,
        conversation,
        recent_messages: list,
        student_id: int,
        course_id: int,
    ) -> dict:
        from app.services.agent_attachment_service import agent_attachment_service
        from app.services.agent_practice_session_service import agent_practice_session_service

        context = agent_memory_service.build_context(conversation, recent_messages)

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

        attachments = agent_attachment_service.list_active_attachments(
            db=db,
            conversation_id=conversation.id,
            student_id=student_id,
            course_id=course_id,
        )
        context["conversation"] = conversation
        context["conversation_id"] = conversation.id
        context["attachments"] = [
            agent_attachment_service.serialize_for_context(a)
            for a in attachments[-10:]
        ]
        context["course_id"] = course_id
        context["student_id"] = student_id
        return context

    def _route_intent(
        self,
        db: Session,
        message: str,
        student_id: int,
        course_id: int,
        context: dict,
    ) -> IntentRouterResult:
        from app.services.agent_rule_gate_service import agent_rule_gate_service
        from app.services.llm_intent_router_service import llm_intent_router_service

        rule_result = agent_rule_gate_service.try_resolve(message, context)
        if rule_result:
            logger.info("LangGraph RuleGate 命中: %s", rule_result.get("reason"))
            return IntentRouterResult.from_rule(rule_result)

        try:
            intent_result = llm_intent_router_service.route(
                db=db,
                message=message,
                course_id=course_id,
                student_id=student_id,
                context=context,
            )
            logger.info(
                "LangGraph LLM 路由完成: domain=%s intent=%s tool=%s confidence=%.2f",
                intent_result.domain,
                intent_result.intent,
                intent_result.tool_name,
                intent_result.confidence,
            )
            return intent_result
        except Exception:
            logger.exception("LangGraph LLM 路由异常，使用 RuleGate fallback")
            fallback = agent_rule_gate_service.fallback_resolve(message, context)
            return IntentRouterResult.from_rule(fallback)

    def _attach_long_term_memory_context(
        self,
        db: Session,
        context: dict,
        student_id: int,
        course_id: int,
        message: str,
        include_graphiti: bool = True,
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
        if include_graphiti:
            graphiti_context = agent_graphiti_memory_service.search_sync(student_id=student_id, course_id=course_id, query=message)
            enriched["graphiti_memory"] = graphiti_context or {"enabled": agent_graphiti_memory_service.is_enabled(), "available": False, "facts": [], "context_text": ""}
            if enriched["graphiti_memory"].get("context_text"):
                enriched["memory_context_text"] = "\n\n".join(
                    item for item in [enriched["memory_context_text"], enriched["graphiti_memory"]["context_text"]] if item
                )
        else:
            enriched["graphiti_memory"] = {"enabled": agent_graphiti_memory_service.is_enabled(), "available": False, "facts": [], "context_text": ""}
        return enriched

    async def _attach_long_term_memory_context_async(
        self,
        db: Session,
        context: dict,
        student_id: int,
        course_id: int,
        message: str,
    ) -> dict:
        enriched = self._attach_long_term_memory_context(
            db=db,
            context=context,
            student_id=student_id,
            course_id=course_id,
            message=message,
            include_graphiti=False,
        )
        from app.services.agent_graphiti_memory_service import agent_graphiti_memory_service

        graphiti_context = await agent_graphiti_memory_service.search(
            student_id=student_id,
            course_id=course_id,
            query=message,
        )
        enriched["graphiti_memory"] = graphiti_context
        if graphiti_context.get("context_text"):
            base = enriched.get("memory_context_text") or ""
            enriched["memory_context_text"] = "\n\n".join(
                item for item in [base, graphiti_context["context_text"]] if item
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
        source_task_id: int | None,
        include_graphiti: bool = True,
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
                source_task_id=source_task_id,
            )
            logger.info(
                "LangGraph memory write completed: student_id=%s course_id=%s written=%s",
                student_id,
                course_id,
                result.get("written_count"),
            )
            if include_graphiti:
                self._sync_memories_to_graphiti(db, student_id, result)
            return result
        except Exception as exc:
            logger.exception("长期记忆自动写入失败，继续返回本轮回答")
            return {"enabled": True, "error": str(exc), "written_count": 0}

    async def _write_long_term_memory_async(
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
        source_task_id: int | None,
    ) -> dict:
        result = self._write_long_term_memory(
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
            source_task_id=source_task_id,
            include_graphiti=False,
        )
        await self._sync_memories_to_graphiti_async(db, student_id, result)
        return result

    def _sync_memories_to_graphiti(self, db: Session, student_id: int, memory_write_result: dict) -> None:
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
            if not memory:
                continue
            agent_graphiti_memory_service.add_memory_episode_sync(
                student_id=student_id,
                course_id=memory.course_id,
                memory=memory,
                reference_time=memory.updated_at,
            )

    async def _sync_memories_to_graphiti_async(self, db: Session, student_id: int, memory_write_result: dict) -> None:
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
            if not memory:
                continue
            await agent_graphiti_memory_service.add_memory_episode(
                student_id=student_id,
                course_id=memory.course_id,
                memory=memory,
                reference_time=memory.updated_at,
            )

    def _detect_and_update_reply_action(
        self,
        db: Session,
        conversation,
        response: dict,
    ) -> dict | None:
        if response.get("skip_reply_action_detection"):
            return None

        from app.services.agent_reply_action_detector import agent_reply_action_detector

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
        return derived_pending_action

    @staticmethod
    def _build_assistant_metadata(
        response: dict,
        intent_result: IntentRouterResult,
        tool_result: dict,
        derived_pending_action: dict | None,
        memory_write_result: dict | None = None,
    ) -> dict:
        return {
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
        }

    def _build_task_result(
        self,
        response: dict,
        intent_result: IntentRouterResult,
        tool_result: dict,
        derived_pending_action: dict | None,
    ) -> dict:
        return {
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
                **self._build_assistant_metadata(
                    response=response,
                    intent_result=intent_result,
                    tool_result=tool_result,
                    derived_pending_action=derived_pending_action,
                    memory_write_result=None,
                ),
                "attachments": response.get("attachments") or [],
                "local_file_operation": response.get("local_file_operation"),
            },
        }

    @staticmethod
    def _build_task_completed_message(task: AgentChatTask, response: dict) -> dict:
        return {
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
        }

    async def _emit_stage(self, state: AgentGraphState, stage: str, text: str) -> None:
        agent_chat_task_service.mark_stage(state["db"], state["task"], stage, text)
        await state["emit"]("stage", {"stage": stage, "text": text})

    async def _check_cancel(self, state: AgentGraphState) -> None:
        check_cancel = state.get("check_cancel")
        if check_cancel:
            await check_cancel(state["db"], state["task"])


agent_graph_service = AgentGraphService()
