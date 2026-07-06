"""
ToolExecutor 工具执行器 — 白名单控制 + 所有工具落地逻辑。

文档参考：docs/LLM语义路由Agent最终架构_详细技术实现文档.md Section 13-14
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint
from app.services.agent_memory_answer_composer_service import agent_memory_answer_composer_service
from app.services.agent_memory_recall_policy_service import agent_memory_recall_policy_service
from app.services.agent_memory_semantics_service import agent_memory_semantics_service

# ================================================================
# 工具白名单（文档 Section 13.2）
# ================================================================

ALLOWED_TOOLS = {
    "qa_answer",
    "generate_exercise_document",
    "start_guided_practice",
    "continue_explanation",
    "provide_code_example",
    "provide_compare_explanation",
    "cancel_pending_action",
    "clarify_exercise_count",
    "clarify",
    "system_identity",
    "small_talk",
    "out_of_scope",
    "generate_inline_practice",
    "grade_practice_answer",
    "continue_inline_practice",
    "local_file_edit_prepare",
    "local_file_edit_confirm",
    "local_file_edit_cancel",
    "create_learning_goal_from_chat",
    "continue_learning_goal_loop",
    "memory_recall",
    "memory_update",
}

logger = logging.getLogger(__name__)


class AgentToolExecutorService:
    """
    工具执行器。

    接收 LLM/规则输出的 intent_result，校验 tool_name 白名单，执行对应工具。
    """

    # ================================================================
    # 主入口（文档 Section 13.3）
    # ================================================================

    def execute(
        self,
        db: Session,
        intent_result,  # IntentRouterResult
        conversation,
        user_message: str,
        student_id: int,
        course_id: int,
        context: dict | None = None,
    ) -> dict:
        """
        根据 intent_result.tool_name 路由到具体工具。

        返回统一结构：
        {
            "type": "answer" | "clarification" | "document",
            "text": "...",
            "qa_id": None,
            "document": None,
            "agent_steps": [],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": False,
        }
        """
        tool_name = intent_result.tool_name

        # 白名单校验（文档 Section 24.2/24.5）
        if tool_name not in ALLOWED_TOOLS:
            return self._clarify(
                "我还不确定你想让我做什么，可以再具体说一下吗？",
                reason=f"未知工具 '{tool_name}'，已降级为 clarify",
            )

        context = context or {}

        # 如果没有正在进行的对话式练习，但当前会话有附件，LLM 偶尔会把
        # “帮我看这几道题是否正确”误判成继续/批改练习。此时应回退到附件答疑。
        if (
            tool_name in {"grade_practice_answer", "continue_inline_practice"}
            and not self._has_active_practice_context(context)
            and self._has_indexed_attachments(context)
        ):
            self._force_attachment_qa(intent_result, reason="no_active_practice_session")
            tool_name = "qa_answer"

        # ── 路由到具体工具 ──
        if tool_name == "qa_answer":
            return self._qa_answer(db, student_id, course_id, user_message, intent_result, context)

        if tool_name == "generate_exercise_document":
            return self._generate_exercise_document(db, student_id, course_id, user_message, intent_result)

        if tool_name == "start_guided_practice":
            return self._start_guided_practice(intent_result)

        if tool_name == "continue_explanation":
            return self._continue_explanation(db, student_id, course_id, intent_result, context)

        if tool_name == "provide_code_example":
            return self._provide_code_example(db, student_id, course_id, intent_result, context)

        if tool_name == "provide_compare_explanation":
            return self._provide_compare_explanation(db, student_id, course_id, intent_result, context)

        if tool_name == "cancel_pending_action":
            return self._cancel_pending_action()

        if tool_name == "generate_inline_practice":
            return self._generate_inline_practice(db, student_id, course_id, user_message, intent_result, conversation, context)

        if tool_name == "grade_practice_answer":
            return self._grade_practice_answer(db, student_id, course_id, user_message, intent_result, conversation, context)

        if tool_name == "continue_inline_practice":
            return self._continue_inline_practice(db, student_id, course_id, user_message, intent_result, conversation, context)

        if tool_name == "clarify_exercise_count":
            return self._clarify_exercise_count(intent_result)

        if tool_name == "clarify":
            question = intent_result.clarification_question or "可以再具体说一下吗？"
            return self._clarify(question)

        if tool_name == "system_identity":
            return self._system_identity()

        if tool_name == "small_talk":
            return self._small_talk()

        if tool_name == "out_of_scope":
            return self._out_of_scope(intent_result)

        if tool_name == "memory_recall":
            return self._memory_recall(context, user_message)

        if tool_name == "memory_update":
            return self._memory_update()

        if tool_name == "local_file_edit_prepare":
            return self._local_file_edit_prepare(
                db=db,
                student_id=student_id,
                course_id=course_id,
                user_message=user_message,
                intent_result=intent_result,
                conversation=conversation,
                context=context,
            )

        if tool_name == "local_file_edit_confirm":
            return self._local_file_edit_confirm(db, student_id, intent_result, context)

        if tool_name == "local_file_edit_cancel":
            return self._local_file_edit_cancel(db, student_id, intent_result, context)

        if tool_name == "create_learning_goal_from_chat":
            return self._create_learning_goal_from_chat(
                db=db,
                student_id=student_id,
                course_id=course_id,
                user_message=user_message,
                intent_result=intent_result,
                conversation=conversation,
                context=context,
            )

        if tool_name == "continue_learning_goal_loop":
            return self._continue_learning_goal_loop(
                db=db,
                student_id=student_id,
                course_id=course_id,
                user_message=user_message,
                intent_result=intent_result,
                conversation=conversation,
                context=context,
            )

        # 兜底
        return self._clarify("我还不确定你想让我做什么，可以再具体说一下吗？")

    @staticmethod
    def _memory_update() -> dict:
        return {
            "type": "answer",
            "text": "好的，我已经记录这次信息更新。",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "更新长期记忆",
                    "detail": "已识别到用户主动更新画像或偏好，回答后会进入长期记忆写入策略。",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    def _memory_recall(self, context: dict, user_message: str) -> dict:
        plan = agent_memory_recall_policy_service.build_plan(user_message, context)
        memories = agent_memory_recall_policy_service.select_memories(context, plan)
        composed = agent_memory_answer_composer_service.compose(
            plan=plan,
            memories=memories,
            context=context,
            user_message=user_message,
        )

        return {
            "type": "answer",
            "text": composed["text"],
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "读取长期记忆",
                    "detail": f"已按读取策略 {composed['category']} 筛选长期记忆，命中 {composed['selected_count']} 条。",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
            "memory_recall": composed,
        }

    @staticmethod
    def _find_memory_value(context: dict, memory_type: str, memory_key: str, value_key: str):
        memory_context = context.get("long_term_memory") or {}
        bucket = memory_context.get(f"{memory_type}_memories") or []
        for memory in bucket:
            if getattr(memory, "memory_key", None) != memory_key:
                continue
            value = getattr(memory, "memory_value_json", None) or {}
            if isinstance(value, dict) and value.get(value_key):
                return value.get(value_key)
            text = getattr(memory, "memory_text", None)
            if text:
                return text
        return None

    @classmethod
    def _build_learning_memory_recall_answer(cls, context: dict, user_message: str) -> str | None:
        memories = cls._learning_related_memories(context, user_message)
        if not memories:
            return None

        topics = []
        raw_lines = []
        for memory in memories:
            topic = cls._extract_learning_topic_from_memory(memory)
            if topic:
                topics.append(topic)
                continue
            memory_text = cls._memory_attr(memory, "memory_text") or ""
            if memory_text:
                raw_lines.append(memory_text)

        topics = cls._dedupe([topic for topic in topics if topic])
        raw_lines = cls._dedupe([line for line in raw_lines if line])

        if topics:
            joined = "、".join(topics[:3])
            if any(word in user_message for word in ["不好", "薄弱", "不会", "不熟", "掌握"]):
                return f"我查到你提到掌握得不太好的知识点是：{joined}。"
            return f"我查到你最近提到的学习知识点是：{joined}。"

        if raw_lines:
            return "我查到和你这个问题相关的学习记忆是：\n" + "\n".join(f"- {line}" for line in raw_lines[:3])
        return None

    @classmethod
    def _learning_related_memories(cls, context: dict, user_message: str) -> list:
        memories = []
        for memory_type in ["learning_state", "episodic", "semantic", "procedural"]:
            memories.extend(cls._memory_bucket(context, memory_type))
        if not memories:
            return []

        query_terms = cls._extract_query_terms(user_message)

        def score(memory) -> float:
            memory_text = cls._memory_attr(memory, "memory_text") or ""
            memory_key = cls._memory_attr(memory, "memory_key") or ""
            value = cls._memory_attr(memory, "memory_value_json") or {}
            haystack = f"{memory_key} {memory_text} {value}".lower()
            value_score = (cls._memory_attr(memory, "importance") or 0) + (cls._memory_attr(memory, "confidence") or 0)
            keyword_score = sum(1 for term in query_terms if term and term.lower() in haystack)
            learning_score = sum(
                1
                for term in ["知识点", "掌握", "薄弱", "不好", "不会", "不熟", "学习", "问过", "最近"]
                if term in haystack
            )
            return value_score + keyword_score * 3 + learning_score

        ranked = sorted(memories, key=score, reverse=True)
        return [memory for memory in ranked if score(memory) > 0][:5]

    @classmethod
    def _format_filtered_memory_recall(cls, context: dict, user_message: str) -> str:
        if cls._is_learning_memory_recall_question(user_message):
            memories = cls._learning_related_memories(context, user_message)
        elif any(word in user_message for word in ["名字", "叫什么"]):
            memories = cls._memory_bucket(context, "profile")
        else:
            memories = []
            for memory_type in ["profile", "preference", "learning_state", "episodic", "semantic", "procedural"]:
                memories.extend(cls._memory_bucket(context, memory_type))

        if not memories:
            return ""
        lines = []
        for memory in memories[:5]:
            memory_text = cls._memory_attr(memory, "memory_text") or ""
            if memory_text:
                lines.append(f"- {memory_text}")
        return "\n".join(cls._dedupe(lines))

    @staticmethod
    def _is_learning_memory_recall_question(text: str) -> bool:
        if not text:
            return False
        learning_markers = ["知识点", "掌握", "薄弱", "弱点", "不会", "不熟", "学习", "课程", "刚刚说", "刚才说"]
        memory_markers = ["记得", "刚刚", "刚才", "之前", "哪个", "什么", "不好", "不太好"]
        return any(item in text for item in learning_markers) and any(item in text for item in memory_markers)

    @classmethod
    def _extract_learning_topic_from_memory(cls, memory) -> str | None:
        value = cls._memory_attr(memory, "memory_value_json") or {}
        if isinstance(value, dict):
            for key in ["topic", "knowledge_point", "knowledge_point_name", "weak_point", "name"]:
                if value.get(key):
                    return str(value[key])
            for key in ["topics", "knowledge_points", "weak_points"]:
                items = value.get(key)
                if isinstance(items, list) and items:
                    return "、".join(str(item) for item in items[:3])

        memory_text = cls._memory_attr(memory, "memory_text") or ""
        for pattern in [
            r"知识点是[“\"]?([^”\"，。；;！？\s]{2,40})",
            r"知识点[：:]?[“\"]([^”\"]{2,40})[”\"]",
            r"[“\"]([^”\"]{2,40})[”\"]这个知识点",
            r"最近(?:问过|学习|提到|说过)[“\"]?([^”\"，。；;！？\s]{2,40})",
            r"([^，。；;！？\s]{2,40})这个知识点(?:掌握|学得|理解)",
        ]:
            match = re.search(pattern, memory_text)
            if match:
                return match.group(1).strip(" “”，。；;！？")
        return None

    @classmethod
    def _memory_bucket(cls, context: dict, memory_type: str) -> list:
        memory_context = context.get("long_term_memory") or {}
        return list(memory_context.get(f"{memory_type}_memories") or [])

    @staticmethod
    def _memory_attr(memory, name: str, default=None):
        if isinstance(memory, dict):
            return memory.get(name, default)
        return getattr(memory, name, default)

    @staticmethod
    def _extract_query_terms(text: str) -> list[str]:
        terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}", text or "")
        stop_words = {
            "我刚刚",
            "刚刚",
            "刚才",
            "哪个",
            "什么",
            "知识点",
            "掌握",
            "不好",
            "不太好",
            "记得",
            "你还",
        }
        return [term for term in terms if term not in stop_words]

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(key)
        return result

    @staticmethod
    def _find_recent_user_name(context: dict) -> str | None:
        recent_messages = context.get("recent_messages") or []
        for item in reversed(recent_messages):
            if item.get("role") != "user":
                continue
            content = item.get("content") or ""
            mention = agent_memory_semantics_service.classify_name_mention(content)
            if mention:
                return mention.value
        return None

    @staticmethod
    def _find_recent_learning_topic(context: dict) -> str | None:
        recent_messages = context.get("recent_messages") or []
        for item in reversed(recent_messages):
            if item.get("role") != "user":
                continue
            content = item.get("content") or ""
            if "记得" in content:
                continue
            for pattern in [
                r"(?:讲一下|解释一下|说一下|介绍一下|讲讲|解释解释)\s*([^，。！？?]{2,40})",
                r"(?:什么是|啥是)\s*([^，。！？?]{2,40})",
            ]:
                match = re.search(pattern, content)
                if match:
                    topic = match.group(1).strip(" ，。,.!！?？；;：:吧呢吗")
                    if topic:
                        return topic
        return None

    # ================================================================
    # 各工具实现（文档 Section 14）
    # ================================================================

    # ── 14.1 qa_answer ────────────────────────────────────────

    def _qa_answer(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        context: dict,
    ) -> dict:
        """调用现有 qa_agent_service.ask()，支持 attachment 上下文（文档 Section 15.1）"""
        from app.services.qa_agent_service import get_qa_agent_service
        from app.services.rag_service import rag_service

        qa_service = get_qa_agent_service()

        # 如果 LLM 识别到指代上一轮，用 topic 补全问题
        question = user_message
        if (
            intent_result.refers_to_previous_message
            and intent_result.topic
            and intent_result.topic not in user_message
        ):
            question = f"结合上一轮提到的“{intent_result.topic}”，{user_message}"

        # 传入最近对话上下文（文档 Section 14.1）
        conversation_context = []
        memory_context_text = context.get("learning_profile_memory_context_text") or context.get("memory_context_text")
        if memory_context_text:
            conversation_context.append({
                "role": "assistant",
                "content": "长期记忆与学习画像上下文：\n" + memory_context_text,
            })
        recent_messages = context.get("recent_messages") or []
        for msg in recent_messages[-6:]:
            conversation_context.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
            })

        # 附件检索（文档 Section 15.1）
        retrieval_scope = getattr(intent_result, "retrieval_scope", "hybrid") or "hybrid"
        target_attachment_ids = getattr(intent_result, "target_attachment_ids", []) or []

        # 如果当前没有附件，强制 course_only
        attachments = context.get("attachments") or []
        if not attachments and retrieval_scope != "course_only":
            retrieval_scope = "course_only"
        elif attachments and self._message_refs_current_attachment(user_message):
            retrieval_scope = "attachments_first"
            if not target_attachment_ids:
                target_attachment_ids = self._recent_indexed_attachment_ids(context, limit=1)

        attachment_chunks = []
        if retrieval_scope in ("attachments_only", "attachments_first", "hybrid"):
            conversation_id = context.get("conversation_id")
            if conversation_id and target_attachment_ids:
                attachment_chunks = rag_service.retrieve_by_attachment_ids(
                    query=user_message,
                    attachment_ids=target_attachment_ids,
                    conversation_id=conversation_id,
                    student_id=student_id,
                    course_id=course_id,
                    top_k=5,
                    db=db,
                )
            elif conversation_id:
                attachment_chunks = rag_service.retrieve_attachments(
                    query=user_message,
                    conversation_id=conversation_id,
                    student_id=student_id,
                    course_id=course_id,
                    top_k=5,
                    db=db,
                )

        result = qa_service.ask(
            db=db,
            student_id=student_id,
            course_id=course_id,
            question=question,
            conversation_context=conversation_context,
            attachment_chunks=attachment_chunks,
            retrieval_scope=retrieval_scope,
        )

        related_ids = result.get("related_knowledge_point_ids") or intent_result.knowledge_point_ids or []
        point_names = self._get_knowledge_point_names(db, related_ids)
        topic = intent_result.topic or ("、".join(point_names) if point_names else None)
        answer_text = result["answer"]

        # 匹配到知识点时，追加练习题邀请（保留旧逻辑兼容）
        pending_action_update = None
        if related_ids and topic:
            answer_text += '\n\n需要我基于“' + topic + '”给你出几道练习题吗？'
            pending_action_update = {
                "type": "confirm_generate_exercise",
                "status": "waiting_user",
                "source": "backend_tool",
                "topic": topic,
                "knowledge_point_ids": related_ids,
                "confirm_action": "clarify_exercise_count",
                "negative_action": "cancel_pending_action",
                "required_slots": ["question_count"],
                "payload": {
                    "default_question_count": 5,
                    "include_answer": True,
                    "include_explanation": True,
                },
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            }

        return {
            "type": "answer",
            "text": answer_text,
            "qa_id": result["qa_id"],
            "document": None,
            "agent_steps": result.get("agent_steps", []),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            "related_knowledge_point_ids": related_ids,
            "pending_action_update": pending_action_update,
            "skip_reply_action_detection": pending_action_update is not None,
            "attachments": self._attachments_by_ids(context, target_attachment_ids),
        }

    @staticmethod
    def _has_active_practice_context(context: dict) -> bool:
        if context.get("active_practice_session"):
            return True
        pending_action = context.get("pending_action") or {}
        return pending_action.get("type") == "inline_practice_waiting_answer"

    @staticmethod
    def _has_indexed_attachments(context: dict) -> bool:
        attachments = context.get("attachments") or []
        return any(a.get("index_status") == "indexed" for a in attachments)

    @staticmethod
    def _recent_indexed_attachment_ids(context: dict, limit: int | None = None) -> list[int]:
        attachments = [
            a for a in (context.get("attachments") or [])
            if a.get("index_status") == "indexed"
        ]
        ids = [int(a["id"]) for a in attachments if a.get("id") is not None]
        if limit:
            return ids[-limit:]
        return ids

    def _force_attachment_qa(self, intent_result, reason: str = "") -> None:
        intent_result.intent = "qa_answer"
        intent_result.resolved_action = "qa_answer"
        intent_result.tool_name = "qa_answer"
        intent_result.requires_attachment_context = True
        intent_result.retrieval_scope = "attachments_first"
        intent_result.reason = f"{intent_result.reason}; fallback_to_attachment_qa:{reason}"

    @staticmethod
    def _message_refs_current_attachment(message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False
        explicit_words = [
            "文档", "附件", "文件", "pdf", "md", "markdown",
            "刚上传", "上传的", "资料里", "根据资料", "根据文档",
        ]
        if any(word in text for word in explicit_words):
            return True
        implicit_patterns = [
            r"这[几\d一二两三四五六七八九十]*道?题",
            r"这[几\d一二两三四五六七八九十]+道",
            r"这些题",
            r"这几道",
            r"我这.*[题道]",
            r"我.*这[几\d一二两三四五六七八九十]+道",
            r"上面.*题",
            r"刚才.*题",
        ]
        return any(re.search(pattern, text) for pattern in implicit_patterns)

    @staticmethod
    def _attachments_by_ids(context: dict, attachment_ids: list[int]) -> list[dict]:
        if not attachment_ids:
            return []
        wanted = {int(item) for item in attachment_ids}
        return [
            a for a in (context.get("attachments") or [])
            if a.get("id") is not None and int(a["id"]) in wanted
        ]

    def _clarify_exercise_count(self, intent_result) -> dict:
        """用户确认要出题后，先追问题目数量。"""
        topic = intent_result.topic or intent_result.tool_args.get("topic") or "刚才这个知识点"
        knowledge_point_ids = intent_result.knowledge_point_ids or intent_result.tool_args.get("knowledge_point_ids") or []
        payload = {
            "default_question_count": intent_result.tool_args.get("default_question_count", 5),
            "include_answer": intent_result.tool_args.get("include_answer", True),
            "include_explanation": intent_result.tool_args.get("include_explanation", True),
        }
        now = datetime.utcnow()
        return {
            "type": "clarification",
            "text": f"好的，我会基于“{topic}”来出题。你想生成几道？是否需要答案和解析？",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "读取上下文",
                    "detail": f"识别到上一轮话题：{topic}；待确认动作：生成练习题",
                    "status": "done",
                },
                {
                    "title": "等待补充参数",
                    "detail": "需要用户补充题目数量",
                    "status": "need_user_input",
                },
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": knowledge_point_ids,
            "pending_action_update": {
                "type": "clarify_exercise_count",
                "status": "waiting_user",
                "source": "tool_executor",
                "topic": topic,
                "knowledge_point_ids": knowledge_point_ids,
                "confirm_action": "generate_exercise_document",
                "negative_action": "cancel_pending_action",
                "payload": payload,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
            },
            "skip_reply_action_detection": True,
        }

    # ── 14.2 generate_exercise_document ───────────────────────

    def _generate_exercise_document(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
    ) -> dict:
        """调用现有 exercise_agent_service.generate()，参数优先级：用户输入 > tool_args > filled_slots > 默认"""
        from app.services.exercise_agent_service import exercise_agent_service

        # 参数优先级（文档 Section 14.2）
        tool_args = intent_result.tool_args or {}

        # 题目数量
        question_count = self._extract_question_count(user_message, default=0)
        if question_count == 0:  # 用户未明确指定数量
            question_count = tool_args.get("question_count", 5)

        # 知识点
        knowledge_point_id = None
        if tool_args.get("knowledge_point_id"):
            knowledge_point_id = tool_args["knowledge_point_id"]
        if intent_result.knowledge_point_ids and not knowledge_point_id:
            knowledge_point_id = intent_result.knowledge_point_ids[0]

        # 从消息匹配知识点
        point = self._match_knowledge_point(db, course_id, user_message)
        if not point and intent_result.topic:
            point = self._match_knowledge_point(db, course_id, intent_result.topic)
        if not point and tool_args.get("topic"):
            point = self._match_knowledge_point(db, course_id, tool_args["topic"])
        if not point and knowledge_point_id:
            point = (
                db.query(KnowledgePoint)
                .filter(
                    KnowledgePoint.id == knowledge_point_id,
                    KnowledgePoint.course_id == course_id,
                )
                .first()
            )

        if not point:
            return self._clarify("我需要知道你想生成哪个知识点的练习题，例如：生成5道有关栈的练习题。")

        topic = intent_result.topic or point.name
        include_answer = tool_args.get("include_answer", True)
        include_explanation = tool_args.get("include_explanation", True)

        # 检查用户是否明确说"不要答案/解析"
        if any(k in user_message for k in ["不要答案", "不带答案", "不需要答案"]):
            include_answer = False
            include_explanation = False
        if any(k in user_message for k in ["不要解析", "不带解析", "不需要解析"]):
            include_explanation = False
        if not include_answer:
            include_explanation = False

        doc, steps = exercise_agent_service.generate(
            db=db,
            user_id=student_id,
            course_id=course_id,
            prompt=user_message,
            question_count=question_count,
            knowledge_point_id=point.id,
            difficulty="adaptive",
            include_answer=include_answer,
            include_explanation=include_explanation,
        )

        return {
            "type": "document",
            "text": f"已生成《{doc.file_name}》。",
            "qa_id": None,
            "document": {
                "id": doc.id,
                "title": doc.title,
                "file_name": doc.file_name,
                "preview_content": doc.preview_content,
                "download_url": f"/api/exercise-generation/{doc.id}/download",
            },
            "agent_steps": steps,
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [point.id],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    # ── 14.3 start_guided_practice ─────────────────────────────

    def _start_guided_practice(self, intent_result) -> dict:
        """对话式小练习，不生成 Markdown 文件（文档 Section 14.3）"""
        topic = intent_result.topic or intent_result.tool_args.get("topic") or "刚才这个知识点"

        return {
            "type": "answer",
            "text": (
                '好的，我们就基于"' + topic + '"做一个小练习。\n\n'
                '第 1 题：请你判断下面这个场景更像栈还是队列，并说一句理由：\n\n'
                '浏览器连续打开 A 页面、B 页面、C 页面，然后点击“返回”时，'
                '会先回到哪个页面？'
            ),
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "读取上下文",
                    "detail": f"用户确认开始小练习；练习话题：{topic}",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": {
                "type": "guided_practice_step",
                "status": "waiting_user",
                "source": "tool_executor",
                "topic": topic,
                "current_step": 1,
                "confirm_action": None,
                "negative_action": "cancel_pending_action",
                "created_at": datetime.utcnow().isoformat(),
            },
            "skip_reply_action_detection": True,
        }

    # ── 14.4 continue_explanation ──────────────────────────────

    def _continue_explanation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        intent_result,
        context: dict,
    ) -> dict:
        """补全问题后调用 qa_answer（文档 Section 14.4）"""
        topic = intent_result.topic or "刚才的问题"
        question = f"请继续解释：{topic}。要求比上一轮更详细、更深入。"
        return self._qa_answer(
            db, student_id, course_id, question,
            intent_result, context,
        )

    # ── 14.5 provide_code_example ──────────────────────────────

    def _provide_code_example(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        intent_result,
        context: dict,
    ) -> dict:
        """补全问题后调用 qa_answer（文档 Section 14.5）"""
        topic = intent_result.topic or "刚才的问题"
        question = f"请用代码示例解释：{topic}。给出可运行的代码并逐行解释。"
        return self._qa_answer(
            db, student_id, course_id, question,
            intent_result, context,
        )

    # ── 14.6 provide_compare_explanation ───────────────────────

    def _provide_compare_explanation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        intent_result,
        context: dict,
    ) -> dict:
        """补全问题后调用 qa_answer（文档 Section 14.6）"""
        topic = intent_result.topic or "刚才的问题"
        question = f"请用对比方式解释：{topic}。从多个维度对比并给出结论。"
        return self._qa_answer(
            db, student_id, course_id, question,
            intent_result, context,
        )

    # ── 14.7 system_identity ───────────────────────────────────

    def _system_identity(self) -> dict:
        """固定模板，不调用 RAG（文档 Section 14.7）"""
        return {
            "type": "answer",
            "text": (
                "我是这个智慧学习辅助系统中的 AI 学习助手，底层接入的是通义千问模型。"
                "我主要帮助你进行课程答疑、知识点讲解、练习题生成和学习巩固。"
            ),
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "系统身份",
                    "detail": "返回固定系统身份说明，不触发 RAG 或学习工具",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,  # 不追加学习邀请
        }

    # ── 14.8 small_talk ────────────────────────────────────────

    def _small_talk(self) -> dict:
        """简短回应并引导学习（文档 Section 14.8）"""
        return {
            "type": "answer",
            "text": (
                "你好，我是你的 AI 学习助手。你可以问我课程知识点、"
                "让我生成练习题，或让我帮你复习薄弱点。"
            ),
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "问候",
                    "detail": "简短回应并引导用户进入学习场景",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    # ── 14.9 out_of_scope ──────────────────────────────────────

    def _out_of_scope(self, intent_result) -> dict:
        """非学习请求边界（文档 Section 14.9）"""
        reason = (intent_result.tool_args or {}).get("message", "该请求与学习辅助场景无关")
        return {
            "type": "answer",
            "text": (
                f"这个请求和学习辅助关系不大，我更适合帮你做课程答疑、"
                f"知识点讲解、练习题生成和复习规划。你可以换成一个学习相关的问题。"
            ),
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "非学习请求边界",
                    "detail": reason,
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    # ── 14.10 generate_inline_practice（文档 Section 12.3） ────────

    def _generate_inline_practice(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        conversation,
        context: dict,
    ) -> dict:
        """生成对话式练习，不生成文档"""
        from app.services.agent_practice_session_service import agent_practice_session_service

        tool_args = intent_result.tool_args or {}
        knowledge_point_ids = (
            intent_result.knowledge_point_ids
            or tool_args.get("knowledge_point_ids")
            or []
        )

        # 参数优先级：用户输入 > tool_args > 默认值
        question_count = self._extract_question_count(user_message, default=0)
        if question_count == 0:
            question_count = tool_args.get("question_count", 5)
        question_count = max(1, min(question_count, 20))

        topic = intent_result.topic or tool_args.get("topic")

        # 从消息匹配知识点
        if not knowledge_point_ids:
            point = self._match_knowledge_point(db, course_id, user_message)
            if not point and topic:
                point = self._match_knowledge_point(db, course_id, topic)
            if point:
                knowledge_point_ids = [point.id]

        # 检查是否要展示答案/解析
        include_answer = tool_args.get("include_answer_on_display", False)
        include_explanation = tool_args.get("include_explanation_on_display", False)
        if any(k in user_message for k in ["不要答案", "不带答案", "不需要答案"]):
            include_answer = False
            include_explanation = False
        if any(k in user_message for k in ["要答案", "带答案", "需要答案"]):
            include_answer = True

        try:
            session, questions, agent_steps = agent_practice_session_service.create_inline_practice(
                db=db,
                conversation_id=conversation.id,
                student_id=student_id,
                course_id=course_id,
                topic=topic,
                knowledge_point_ids=knowledge_point_ids,
                question_count=question_count,
                difficulty=tool_args.get("difficulty", "adaptive"),
                include_answer_on_display=include_answer,
                include_explanation_on_display=include_explanation,
            )
        except Exception as exc:
            logger.exception("生成对话式练习失败")
            return self._clarify(f"练习题生成失败：{exc}，请稍后重试。")

        # 构建展示文本
        lines = [f'好的，我用文字给你出 {session.question_count} 道题，不附答案和解析。你可以直接回复「第一题选 A」。', ""]
        for q in questions:
            lines.append(f"第 {q.question_no} 题：{q.stem}")
            options = q.options_json or {}
            for key in ["A", "B", "C", "D"]:
                if key in options:
                    lines.append(f"{key}. {options[key]}")
            lines.append("")

        text = "\n".join(lines).strip()

        now = datetime.utcnow()
        return {
            "type": "answer",
            "text": text,
            "qa_id": None,
            "document": None,
            "agent_steps": agent_steps,
            "retrieved_chunks": [],
            "related_knowledge_point_ids": knowledge_point_ids,
            "practice_session": {
                "session_id": session.id,
                "topic": session.topic,
                "status": session.status,
                "question_count": session.question_count,
                "answered_count": session.answered_count,
                "correct_count": session.correct_count,
                "current_question_no": session.current_question_no,
            },
            "pending_action_update": {
                "type": "inline_practice_waiting_answer",
                "session_id": session.id,
                "topic": topic,
                "knowledge_point_ids": knowledge_point_ids,
                "current_question_no": 1,
                "confirm_action": "grade_practice_answer",
                "negative_action": "cancel_pending_action",
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=60)).isoformat(),
            },
            "skip_reply_action_detection": True,
        }

    # ── 14.11 grade_practice_answer（文档 Section 12.4） ──────────

    def _grade_practice_answer(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        conversation,
        context: dict,
    ) -> dict:
        """批改对话式练习答案"""
        from app.services.agent_practice_session_service import agent_practice_session_service

        result = agent_practice_session_service.grade_answer(
            db=db,
            conversation_id=conversation.id,
            student_id=student_id,
            course_id=course_id,
            message=user_message,
        )
        return result

    # ── 14.12 continue_inline_practice（文档 Section 12.5） ───────

    def _continue_inline_practice(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        conversation,
        context: dict,
    ) -> dict:
        """继续当前对话式练习"""
        from app.services.agent_practice_session_service import agent_practice_session_service

        session = agent_practice_session_service.get_active_session(
            db=db,
            conversation_id=conversation.id,
            student_id=student_id,
            course_id=course_id,
        )

        if not session:
            return {
                "type": "answer",
                "text": "当前没有进行中的对话式练习。你可以让我出几道题，例如：\"帮我出3道关于数据结构的单选题，文字发给我就行\"。",
                "qa_id": None,
                "document": None,
                "agent_steps": [
                    {"title": "查找练习", "detail": "未找到 active practice session", "status": "done"}
                ],
                "retrieved_chunks": [],
                "related_knowledge_point_ids": [],
                "pending_action_update": None,
                "skip_reply_action_detection": True,
            }

        if session.current_question_no:
            # 找到当前题目
            from app.models.agent_practice import AgentPracticeQuestion
            question = (
                db.query(AgentPracticeQuestion)
                .filter(
                    AgentPracticeQuestion.session_id == session.id,
                    AgentPracticeQuestion.question_no == session.current_question_no,
                )
                .first()
            )
            if question:
                options = question.options_json or {}
                lines = [f"请继续回答第 {session.current_question_no} 题：{question.stem}"]
                for key in ["A", "B", "C", "D"]:
                    if key in options:
                        lines.append(f"{key}. {options[key]}")
                text = "\n".join(lines)
            else:
                text = f"请继续回答第 {session.current_question_no} 题。"
        else:
            text = "当前练习已完成。需要我再出一组新的练习题吗？"

        return {
            "type": "answer",
            "text": text,
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {"title": "继续练习", "detail": f"Session #{session.id}，当前第{session.current_question_no}题", "status": "done"}
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": session.knowledge_point_ids or [],
            "practice_session": {
                "session_id": session.id,
                "topic": session.topic,
                "status": session.status,
                "question_count": session.question_count,
                "answered_count": session.answered_count,
                "correct_count": session.correct_count,
                "current_question_no": session.current_question_no,
            },
            "pending_action_update": {
                "type": "inline_practice_waiting_answer",
                "session_id": session.id,
                "current_question_no": session.current_question_no,
                "confirm_action": "grade_practice_answer",
                "negative_action": "cancel_pending_action",
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(minutes=60)).isoformat(),
            } if session.current_question_no else None,
            "skip_reply_action_detection": True,
        }

    # ── cancel_pending_action ──────────────────────────────────

    def _cancel_pending_action(self) -> dict:
        # 如果有 active practice session，也将其取消
        # 注意：实际 cancel 由 Orchestrator 层处理，这里只返回提示
        return {
            "type": "answer",
            "text": "好的，那我们先不继续这个操作。你可以继续问我刚才这个知识点的问题。",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "取消待确认任务",
                    "detail": "用户取消当前待确认动作",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "practice_session": None,
            "practice_result": None,
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    # ── local_file_edit_prepare（文档 Section 14.3） ──────────────

    def _local_file_edit_prepare(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        conversation,
        context: dict,
    ) -> dict:
        """创建本地文件修改预览"""
        from app.services.agent_local_file_edit_service import agent_local_file_edit_service

        tool_args = intent_result.tool_args or {}
        file_path = tool_args.get("file_path")
        instruction = tool_args.get("instruction") or user_message

        if not file_path:
            return self._clarify("请提供要修改的本地文件完整路径，并确保它在允许访问的目录内。")

        try:
            operation = agent_local_file_edit_service.create_preview(
                db=db,
                student_id=student_id,
                course_id=course_id,
                conversation_id=getattr(conversation, "id", None),
                task_id=context.get("task_id"),
                user_message_id=context.get("user_message_id"),
                assistant_message_id=context.get("assistant_message_id"),
                file_path=file_path,
                instruction=instruction,
            )
        except ValueError as e:
            return self._clarify(str(e))

        return {
            "type": "local_file_edit_preview",
            "text": "我已经生成了文件修改预览，请你确认后再写入本地文件。",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "识别文件修改需求",
                    "detail": "检测到用户希望修改本地文件",
                    "status": "done",
                },
                {
                    "title": "安全校验",
                    "detail": "文件路径、扩展名、大小均已通过校验",
                    "status": "done",
                },
                {
                    "title": "生成修改预览",
                    "detail": "已生成 Diff，等待用户确认",
                    "status": "need_user_input",
                },
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": {
                "type": "local_file_edit_confirmation",
                "status": "waiting_user",
                "operation_uuid": operation["operation_uuid"],
                "confirm_action": "local_file_edit_confirm",
                "negative_action": "local_file_edit_cancel",
                "payload": {
                    "operation_uuid": operation["operation_uuid"],
                    "original_sha256": operation["original_sha256"],
                },
            },
            "skip_reply_action_detection": True,
            "local_file_operation": operation,
        }

    def _resolve_local_file_operation_args(self, intent_result, context: dict) -> tuple[str | None, str | None]:
        tool_args = intent_result.tool_args or {}
        pending_action = context.get("pending_action") or {}
        payload = pending_action.get("payload") or {}
        operation_uuid = (
            tool_args.get("operation_uuid")
            or payload.get("operation_uuid")
            or pending_action.get("operation_uuid")
        )
        original_sha256 = (
            tool_args.get("original_sha256")
            or tool_args.get("expected_original_sha256")
            or payload.get("original_sha256")
            or payload.get("expected_original_sha256")
            or pending_action.get("original_sha256")
            or pending_action.get("expected_original_sha256")
        )
        return operation_uuid, original_sha256

    def _local_file_edit_confirm(self, db: Session, student_id: int, intent_result, context: dict) -> dict:
        """确认上一轮本地文件修改预览并写入文件。"""
        from app.services.agent_local_file_edit_service import agent_local_file_edit_service

        operation_uuid, original_sha256 = self._resolve_local_file_operation_args(intent_result, context)
        if not operation_uuid:
            return self._clarify("我没有找到正在等待确认的文件修改预览，请重新发起文件修改。")

        try:
            before = agent_local_file_edit_service.get_operation(db, operation_uuid, student_id)
            expected_sha = original_sha256 or before.get("original_sha256")
            result = agent_local_file_edit_service.confirm_operation(
                db=db,
                operation_uuid=operation_uuid,
                student_id=student_id,
                expected_original_sha256=expected_sha,
            )
            operation = agent_local_file_edit_service.get_operation(db, operation_uuid, student_id)
        except ValueError as e:
            return self._clarify(str(e))

        return {
            "type": "local_file_edit_result",
            "text": result.get("message") or "文件已修改并完成备份。",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "确认修改",
                    "detail": "用户已确认写入本地文件",
                    "status": "done",
                },
                {
                    "title": "备份并写入",
                    "detail": "已备份原文件并完成原子写入",
                    "status": "done",
                },
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
            "local_file_operation": {
                **before,
                **operation,
                **result,
            },
        }

    def _local_file_edit_cancel(self, db: Session, student_id: int, intent_result, context: dict) -> dict:
        """取消上一轮本地文件修改预览。"""
        from app.services.agent_local_file_edit_service import agent_local_file_edit_service

        operation_uuid, _ = self._resolve_local_file_operation_args(intent_result, context)
        if not operation_uuid:
            return self._clarify("我没有找到正在等待确认的文件修改预览，请重新发起文件修改。")

        try:
            before = agent_local_file_edit_service.get_operation(db, operation_uuid, student_id)
            result = agent_local_file_edit_service.cancel_operation(
                db=db,
                operation_uuid=operation_uuid,
                student_id=student_id,
                reason="chat_cancel",
            )
            operation = agent_local_file_edit_service.get_operation(db, operation_uuid, student_id)
        except ValueError as e:
            return self._clarify(str(e))

        return {
            "type": "local_file_edit_result",
            "text": result.get("message") or "已取消，本地文件没有被修改。",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "取消修改",
                    "detail": "用户取消了本地文件修改预览",
                    "status": "done",
                },
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
            "local_file_operation": {
                **before,
                **operation,
                **result,
            },
        }

    # ── create_learning_goal_from_chat（文档 Section 14.3） ──────

    def _create_learning_goal_from_chat(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        conversation,
        context: dict,
    ) -> dict:
        """从对话创建学习目标（文档 Section 14）"""
        from app.services.agent_goal_chat_creation_service import agent_goal_chat_creation_service

        return agent_goal_chat_creation_service.create_from_chat(
            db=db,
            student_id=student_id,
            current_course_id=course_id,
            user_message=user_message,
            tool_args=intent_result.tool_args or {},
            conversation_id=conversation.id if conversation else None,
        )

    # ── continue_learning_goal_loop（文档 Section 21） ──────

    def _continue_learning_goal_loop(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        conversation,
        context: dict,
    ) -> dict:
        """从对话触发多轮自主推进（文档 Section 21）"""
        from app.services.agent_goal_loop_service import agent_goal_loop_service

        tool_args = intent_result.tool_args or {}
        goal_id = tool_args.get("goal_id")
        goal_title_hint = tool_args.get("goal_title_hint")
        auto_select = tool_args.get("auto_select_latest_goal", True)
        max_iterations = tool_args.get("max_iterations", 3)

        # 如果未提供 goal_id，查询当前课程的 active 目标
        if not goal_id:
            from app.services.agent_goal_service import agent_goal_service
            active_goals = agent_goal_service.list_goals(
                db=db,
                student_id=student_id,
                course_id=course_id,
                status="active",
            )

            # 按 title 过滤（如果有 hint）
            matching = []
            if goal_title_hint and active_goals:
                for g in active_goals:
                    if goal_title_hint.lower() in g["title"].lower():
                        matching.append(g)

            if matching and len(matching) == 1:
                goal_id = matching[0]["id"]
            elif auto_select and active_goals and len(active_goals) == 1:
                goal_id = active_goals[0]["id"]
            elif active_goals and len(active_goals) > 1:
                # 多个目标，列出让用户选择
                goal_titles = [g["title"] for g in active_goals[:5]]
                title_list = "、".join(f"「{t}」" for t in goal_titles)
                return self._clarify(
                    f"你当前有 {len(active_goals)} 个进行中的目标：{title_list}。请问你想推进哪一个？"
                )
            elif not active_goals:
                return self._clarify(
                    "你当前课程下还没有进行中的学习目标。你可以先创建一个目标，"
                    "例如说「帮我制定一份期末复习计划，目标 80 分」。"
                )

        if not goal_id:
            return self._clarify("请告诉我你想推进哪个学习目标。")

        try:
            loop_result = agent_goal_loop_service.run_goal_loop(
                db=db,
                goal_id=goal_id,
                student_id=student_id,
                course_id=course_id,
                conversation_id=conversation.id if conversation else None,
                max_iterations=max_iterations,
                trigger_type="chat",
            )

            # 构建 agent_steps
            agent_steps = []
            for it in loop_result.get("iterations", []):
                agent_steps.append({
                    "title": f"第 {it['iteration_no']} 轮",
                    "detail": it.get("action_summary") or it.get("decision_type", ""),
                    "status": "done" if it.get("status") == "completed" else "need_user_input",
                })

            return {
                "type": "goal_loop_result",
                "text": loop_result["summary"],
                "goal_loop": loop_result,
                "agent_steps": agent_steps,
                "skip_reply_action_detection": True,
            }
        except ValueError as e:
            return self._clarify(str(e))

    # ── clarify ────────────────────────────────────────────────

    def _clarify(self, text: str, reason: str = "") -> dict:
        return {
            "type": "clarification",
            "text": text,
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "需要澄清",
                    "detail": reason or "用户输入不明确，等待用户补充具体需求",
                    "status": "need_user_input",
                }
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    # ================================================================
    # 流式执行（文档 Section 10）
    # ================================================================

    async def execute_streaming(
        self,
        db: Session,
        intent_result,
        conversation,
        user_message: str,
        student_id: int,
        course_id: int,
        context: dict | None = None,
        emit=None,
        check_cancel=None,
        task=None,
    ) -> dict:
        """
        流式工具执行入口（文档 Section 10.1）。

        对 LLM 生成类工具走 token 流式，其他工具走 tool_result。
        """
        tool_name = intent_result.tool_name
        context = context or {}

        # 白名单校验
        if tool_name not in ALLOWED_TOOLS:
            result = self._clarify(
                "我还不确定你想让我做什么，可以再具体说一下吗？",
                reason=f"未知工具 '{tool_name}'，已降级为 clarify",
            )
            await self._emit_tool_result(result, emit)
            return result

        # 误判回退到附件答疑
        if (
            tool_name in {"grade_practice_answer", "continue_inline_practice"}
            and not self._has_active_practice_context(context)
            and self._has_indexed_attachments(context)
        ):
            self._force_attachment_qa(intent_result, reason="no_active_practice_session")
            tool_name = "qa_answer"

        # ── LLM 流式工具（文档 Section 8.1） ──
        if tool_name == "qa_answer":
            return await self._qa_answer_stream(
                db, student_id, course_id, user_message, intent_result, context,
                emit, check_cancel, task,
            )

        if tool_name == "continue_explanation":
            topic = intent_result.topic or "刚才的问题"
            question = f"请继续解释：{topic}。要求比上一轮更详细、更深入。"
            return await self._qa_answer_stream(
                db, student_id, course_id, question, intent_result, context,
                emit, check_cancel, task,
            )

        if tool_name == "provide_code_example":
            topic = intent_result.topic or "刚才的问题"
            question = f"请用代码示例解释：{topic}。给出可运行的代码并逐行解释。"
            return await self._qa_answer_stream(
                db, student_id, course_id, question, intent_result, context,
                emit, check_cancel, task,
            )

        if tool_name == "provide_compare_explanation":
            topic = intent_result.topic or "刚才的问题"
            question = f"请用对比方式解释：{topic}。从多个维度对比并给出结论。"
            return await self._qa_answer_stream(
                db, student_id, course_id, question, intent_result, context,
                emit, check_cancel, task,
            )

        # ── 本地文件修改预览：同步执行，不走 token 流式（文档 Section 18） ──
        if tool_name == "local_file_edit_prepare":
            result = self._local_file_edit_prepare(
                db=db,
                student_id=student_id,
                course_id=course_id,
                user_message=user_message,
                intent_result=intent_result,
                conversation=conversation,
                context=context,
            )
            await self._emit_tool_result(result, emit)
            return result

        # ── 非 LLM 工具：同步执行后用 tool_result 或分段 token（文档 Section 8.2） ──
        tool_result = self.execute(
            db=db,
            intent_result=intent_result,
            conversation=conversation,
            user_message=user_message,
            student_id=student_id,
            course_id=course_id,
            context=context,
        )

        # 根据文本长度决定发送方式
        text = tool_result.get("text") or ""
        if len(text) <= 200:
            # 短文本：直接 tool_result
            await self._emit_tool_result(tool_result, emit)
        else:
            # 长文本：分段 token 模拟流式，体验更统一
            await self._emit_text_as_tokens(text, emit)
            # 额外发送 practice_session / document 等结构化字段
            extra = {}
            if tool_result.get("practice_session"):
                extra["practice_session"] = tool_result["practice_session"]
            if tool_result.get("document"):
                extra["document"] = tool_result["document"]
            if extra:
                await emit("tool_result", {
                    "text": text,
                    "message_type": tool_result.get("type", "answer"),
                    **extra,
                })

        return tool_result

    # ── qa_answer 流式（文档 Section 10.2） ─────────────────

    async def _qa_answer_stream(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        context: dict,
        emit,
        check_cancel,
        task,
    ) -> dict:
        """流式调用 qa_agent_service.ask_stream()，复用附件检索和上下文补全逻辑"""
        from app.services.qa_agent_service import get_qa_agent_service
        from app.services.rag_service import rag_service

        qa_service = get_qa_agent_service()

        question = user_message
        if (
            intent_result.refers_to_previous_message
            and intent_result.topic
            and intent_result.topic not in user_message
        ):
            question = f"结合上一轮提到的「{intent_result.topic}」，{user_message}"

        conversation_context = []
        memory_context_text = context.get("learning_profile_memory_context_text") or context.get("memory_context_text")
        if memory_context_text:
            conversation_context.append({
                "role": "assistant",
                "content": "长期记忆与学习画像上下文：\n" + memory_context_text,
            })
        recent_messages = context.get("recent_messages") or []
        for msg in recent_messages[-6:]:
            conversation_context.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
            })

        retrieval_scope = getattr(intent_result, "retrieval_scope", "hybrid") or "hybrid"
        target_attachment_ids = getattr(intent_result, "target_attachment_ids", []) or []

        attachments = context.get("attachments") or []
        if not attachments and retrieval_scope != "course_only":
            retrieval_scope = "course_only"
        elif attachments and self._message_refs_current_attachment(user_message):
            retrieval_scope = "attachments_first"
            if not target_attachment_ids:
                target_attachment_ids = self._recent_indexed_attachment_ids(context, limit=1)

        attachment_chunks = []
        if retrieval_scope in ("attachments_only", "attachments_first", "hybrid"):
            conversation_id = context.get("conversation_id")
            if conversation_id and target_attachment_ids:
                attachment_chunks = rag_service.retrieve_by_attachment_ids(
                    query=user_message,
                    attachment_ids=target_attachment_ids,
                    conversation_id=conversation_id,
                    student_id=student_id,
                    course_id=course_id,
                    top_k=5,
                    db=db,
                )
            elif conversation_id:
                attachment_chunks = rag_service.retrieve_attachments(
                    query=user_message,
                    conversation_id=conversation_id,
                    student_id=student_id,
                    course_id=course_id,
                    top_k=5,
                    db=db,
                )

        # 流式生成
        result = await qa_service.ask_stream(
            db=db,
            student_id=student_id,
            course_id=course_id,
            question=question,
            conversation_context=conversation_context,
            attachment_chunks=attachment_chunks,
            retrieval_scope=retrieval_scope,
            emit=emit,
            check_cancel=check_cancel,
            task=task,
        )

        related_ids = result.get("related_knowledge_point_ids") or intent_result.knowledge_point_ids or []
        point_names = self._get_knowledge_point_names(db, related_ids)
        topic = intent_result.topic or ("、".join(point_names) if point_names else None)
        answer_text = result["answer"]

        pending_action_update = None
        if related_ids and topic:
            answer_text += '\n\n需要我基于"' + topic + '"给你出几道练习题吗？'
            pending_action_update = {
                "type": "confirm_generate_exercise",
                "status": "waiting_user",
                "source": "backend_tool",
                "topic": topic,
                "knowledge_point_ids": related_ids,
                "confirm_action": "clarify_exercise_count",
                "negative_action": "cancel_pending_action",
                "required_slots": ["question_count"],
                "payload": {
                    "default_question_count": 5,
                    "include_answer": True,
                    "include_explanation": True,
                },
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            }

        return {
            "type": "answer",
            "text": answer_text,
            "qa_id": result["qa_id"],
            "document": None,
            "agent_steps": result.get("agent_steps", []),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            "related_knowledge_point_ids": related_ids,
            "pending_action_update": pending_action_update,
            "skip_reply_action_detection": pending_action_update is not None,
            "attachments": self._attachments_by_ids(context, target_attachment_ids),
        }

    # ── 流式发送辅助（文档 Section 8.2） ──────────────────

    @staticmethod
    async def _emit_tool_result(result: dict, emit) -> None:
        """发送 tool_result 事件（文档 Section 4.1）"""
        if emit is None:
            return
        await emit("tool_result", {
            "text": result.get("text") or "",
            "message_type": result.get("type", "answer"),
            "local_file_operation": result.get("local_file_operation"),
            "practice_session": result.get("practice_session"),
            "practice_result": result.get("practice_result"),
            "document": result.get("document"),
            "attachments": result.get("attachments") or [],
            "learning_goal": result.get("learning_goal"),
            "goal_plan": result.get("goal_plan"),
            "goal_loop": result.get("goal_loop"),
        })

    @staticmethod
    async def _emit_text_as_tokens(text: str, emit, chunk_size: int = 8) -> None:
        """将文本切成小块模拟 token 流式输出（文档 Section 8.2）"""
        if emit is None:
            return
        for i in range(0, len(text), chunk_size):
            await emit("token", {"text": text[i:i + chunk_size]})
            await asyncio.sleep(0.01)

    # ================================================================
    # 工具方法
    # ================================================================

    @staticmethod
    def _extract_question_count(message: str, default: int = 5) -> int:
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

    @staticmethod
    def _match_knowledge_point(db: Session, course_id: int, message: str):
        points = db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id).all()
        for point in points:
            if point.name in message:
                return point
        return None

    @staticmethod
    def _get_knowledge_point_names(db: Session, knowledge_point_ids: list[int]) -> list[str]:
        if not knowledge_point_ids:
            return []
        points = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(knowledge_point_ids)).all()
        return [point.name for point in points]


agent_tool_executor_service = AgentToolExecutorService()
