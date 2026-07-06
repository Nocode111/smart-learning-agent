"""
Automatic long-term memory extraction service.

This stage follows the LangMem memory-manager pattern: extract durable facts,
preferences, and learning events from an interaction, then merge them into the
project-owned MySQL memory tables.
"""

import hashlib
import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_memory import AgentMemory
from app.models.knowledge_point import KnowledgePoint
from app.services.agent_long_term_memory_service import (
    VALID_MEMORY_TYPES,
    agent_long_term_memory_service,
)
from app.services.agent_memory_semantics_service import agent_memory_semantics_service
from app.services.qwen_client import qwen_client

logger = logging.getLogger(__name__)

CourseScope = Literal["global", "course"]


class AgentMemoryCandidate(BaseModel):
    memory_type: str = Field(description="profile/preference/learning_state/episodic/semantic/procedural")
    memory_key: str
    memory_text: str
    memory_value_json: Any = None
    confidence: float = 0.8
    importance: float = 0.5
    course_scope: CourseScope = "course"
    source: str = "rule"
    evidence: str | None = None
    utterance_type: str = "unknown"
    action: str = "upsert"


class AgentMemoryExtractionService:
    """Extracts and persists durable memories after each Agent turn."""

    def extract_and_persist(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        tool_result: dict | None,
        response: dict | None,
        context: dict | None = None,
        conversation_id: int | None = None,
        source_message_id: int | None = None,
        source_task_id: int | None = None,
    ) -> dict:
        candidates = self.extract_candidates(
            db=db,
            student_id=student_id,
            course_id=course_id,
            user_message=user_message,
            intent_result=intent_result,
            tool_result=tool_result or {},
            response=response or {},
            context=context or {},
        )
        candidates = self._dedupe_candidates(candidates)
        limit = max(1, min(settings.agent_memory_extract_max_candidates, 20))
        candidates = candidates[:limit]

        written: list[AgentMemory] = []
        rejected: list[dict] = []
        decisions: list[dict] = []
        from app.services.agent_memory_write_policy_service import agent_memory_write_policy_service

        for candidate in candidates:
            target_course_id = course_id if candidate.course_scope == "course" else None
            decision = agent_memory_write_policy_service.evaluate(
                db=db,
                student_id=student_id,
                course_id=target_course_id,
                candidate=candidate,
                user_message=user_message,
                intent_result=intent_result,
                context=context or {},
            )
            decisions.append(decision.model_dump())
            if not decision.allow:
                agent_long_term_memory_service.record_policy_rejection(
                    db=db,
                    student_id=student_id,
                    course_id=target_course_id,
                    candidate_json=candidate.model_dump(),
                    reason=decision.reason,
                    source_message_id=source_message_id,
                    source_task_id=source_task_id,
                )
                rejected.append(
                    {
                        "memory_type": candidate.memory_type,
                        "memory_key": candidate.memory_key,
                        "reason": decision.reason,
                    }
                )
                continue

            memory = agent_long_term_memory_service.upsert_memory(
                db=db,
                student_id=student_id,
                course_id=target_course_id,
                memory_type=candidate.memory_type,
                memory_key=candidate.memory_key,
                memory_text=candidate.memory_text,
                memory_value_json=candidate.memory_value_json,
                confidence=candidate.confidence,
                importance=candidate.importance,
                source_type=f"auto_extract:{candidate.source}",
                source_id=source_message_id or source_task_id,
                reason=f"auto_extract:{candidate.source};policy:{decision.action}",
                source_message_id=source_message_id,
                source_task_id=source_task_id,
            )
            written.append(memory)

        return {
            "enabled": True,
            "conversation_id": conversation_id,
            "candidate_count": len(candidates),
            "written_count": len(written),
            "rejected_count": len(rejected),
            "memory_ids": [memory.id for memory in written],
            "memory_keys": [candidate.memory_key for candidate in candidates],
            "rejected": rejected,
            "policy_decisions": decisions,
        }

    def extract_candidates(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        user_message: str,
        intent_result,
        tool_result: dict,
        response: dict,
        context: dict,
    ) -> list[AgentMemoryCandidate]:
        candidates = self._extract_rule_candidates(
            db=db,
            course_id=course_id,
            user_message=user_message,
            intent_result=intent_result,
            tool_result=tool_result,
            response=response,
        )

        if settings.agent_memory_extract_use_llm and self._should_run_semantic_extractor(
            user_message=user_message,
            intent_result=intent_result,
            response=response,
        ):
            try:
                if settings.agent_memory_extract_engine == "langmem":
                    candidates.extend(
                        self._extract_with_langmem(
                            context=context,
                            user_message=user_message,
                            response=response,
                        )
                    )
                else:
                    candidates.extend(
                        self._extract_with_qwen_json(
                            context=context,
                            user_message=user_message,
                            intent_result=intent_result,
                            tool_result=tool_result,
                            response=response,
                        )
                    )
            except Exception:
                logger.exception("Semantic memory extraction failed; rule candidates will still be used")

        return self._normalize_candidates(candidates)

    # ================================================================
    # Deterministic extraction
    # ================================================================

    def _extract_rule_candidates(
        self,
        db: Session,
        course_id: int,
        user_message: str,
        intent_result,
        tool_result: dict,
        response: dict,
    ) -> list[AgentMemoryCandidate]:
        text = (user_message or "").strip()
        candidates: list[AgentMemoryCandidate] = []

        name_mention = agent_memory_semantics_service.classify_name_mention(text)
        if name_mention:
            candidates.append(
                AgentMemoryCandidate(
                    memory_type="profile",
                    memory_key="name",
                    memory_text=f"用户的名字是{name_mention.value}。",
                    memory_value_json={"name": name_mention.value},
                    confidence=0.95,
                    importance=0.9,
                    course_scope="global",
                    source="rule:name",
                    evidence=name_mention.evidence,
                    utterance_type=name_mention.utterance_type,
                    action=name_mention.action,
                )
            )

        if self._states_student_identity(text):
            candidates.append(
                AgentMemoryCandidate(
                    memory_type="profile",
                    memory_key="role",
                    memory_text="用户当前身份是学生。",
                    memory_value_json={"role": "student"},
                    confidence=0.9,
                    importance=0.65,
                    course_scope="global",
                    source="rule:profile",
                    evidence=self._matched_text(text, ["我是学生", "我现在是学生", "我是一名学生"]),
                    utterance_type="self_statement",
                )
            )

        if self._prefers_name_in_reply(text):
            candidates.append(
                AgentMemoryCandidate(
                    memory_type="preference",
                    memory_key="reply_use_user_name",
                    memory_text="用户偏好后续回答中带上他的名字或称呼。",
                    memory_value_json={"use_user_name_in_reply": True},
                    confidence=0.95,
                    importance=0.85,
                    course_scope="global",
                    source="rule:preference",
                    evidence=text[:200],
                    utterance_type="preference_instruction",
                )
            )

        for explicit_memory in self._extract_explicit_remember_requests(text):
            candidates.append(explicit_memory)

        learning_preference = self._extract_learning_preference(text)
        if learning_preference:
            candidates.append(learning_preference)

        weakness_topic = self._extract_self_reported_weakness(text)
        if weakness_topic:
            candidates.append(
                self._build_learning_state_candidate(
                    topic=weakness_topic,
                    state="weak",
                    signal="self_reported_weakness",
                    memory_text=f"用户最近表示“{weakness_topic}”这个知识点掌握得不好。",
                    evidence=text[:200],
                    confidence=0.9,
                    importance=0.85,
                )
            )

        mastery_topic = self._extract_self_reported_mastery(
            text,
            fallback_topic=getattr(intent_result, "topic", None),
        )
        if mastery_topic:
            candidates.append(
                self._build_learning_state_candidate(
                    topic=mastery_topic,
                    state="mastered",
                    signal="self_reported_mastery",
                    memory_text=f"用户最近表示已经掌握“{mastery_topic}”这个知识点。",
                    evidence=text[:200],
                    confidence=0.88,
                    importance=0.82,
                )
            )

        learning_goal = self._extract_learning_goal(text)
        if learning_goal:
            goal_text, goal_value = learning_goal
            candidates.append(
                AgentMemoryCandidate(
                    memory_type="semantic",
                    memory_key=f"learning_goal:{self._short_key(goal_text)}",
                    memory_text=f"用户的学习目标是：{goal_text}。",
                    memory_value_json=goal_value,
                    confidence=0.88,
                    importance=0.88,
                    course_scope="course",
                    source="rule:learning_goal",
                    evidence=text[:200],
                    utterance_type="self_statement",
                )
            )

        practice_weakness = self._extract_practice_weakness(
            tool_result=tool_result,
            response=response,
            intent_result=intent_result,
        )
        if practice_weakness:
            topic, wrong_count = practice_weakness
            candidates.append(
                self._build_learning_state_candidate(
                    topic=topic,
                    state="weak",
                    signal="practice_wrong_streak",
                    memory_text=f"用户最近在“{topic}”练习中连续答错，可能是薄弱点。",
                    evidence=f"practice_wrong_streak:{wrong_count}",
                    confidence=0.82,
                    importance=0.86,
                    extra_value={"wrong_count": wrong_count},
                )
            )

        topic_info = self._extract_learning_topic(
            db=db,
            course_id=course_id,
            user_message=text,
            intent_result=intent_result,
            tool_result=tool_result,
            response=response,
        )
        if topic_info:
            topic, knowledge_point_ids = topic_info
            candidates.append(
                AgentMemoryCandidate(
                    memory_type="episodic",
                    memory_key="last_asked_topic",
                    memory_text=f"用户最近问过的知识点是“{topic}”。",
                    memory_value_json={
                        "topic": topic,
                        "knowledge_point_ids": knowledge_point_ids,
                    },
                    confidence=0.9,
                    importance=0.75,
                    course_scope="course",
                    source="rule:learning_topic",
                    evidence=text[:200],
                    utterance_type="learning_question",
                )
            )
            candidates.append(
                AgentMemoryCandidate(
                    memory_type="episodic",
                    memory_key=f"asked_topic:{self._short_key(topic)}",
                    memory_text=f"用户曾询问过“{topic}”这个知识点。",
                    memory_value_json={
                        "topic": topic,
                        "knowledge_point_ids": knowledge_point_ids,
                    },
                    confidence=0.85,
                    importance=0.55,
                    course_scope="course",
                    source="rule:learning_topic",
                    evidence=text[:200],
                    utterance_type="learning_question",
                )
            )

        return candidates

    def _build_learning_state_candidate(
        self,
        topic: str,
        state: str,
        signal: str,
        memory_text: str,
        evidence: str,
        confidence: float,
        importance: float,
        extra_value: dict | None = None,
    ) -> AgentMemoryCandidate:
        value = {
            "topic": topic,
            "state": state,
            "signal": signal,
        }
        if extra_value:
            value.update(extra_value)
        return AgentMemoryCandidate(
            memory_type="learning_state",
            memory_key=f"learning_state:{self._short_key(topic)}",
            memory_text=memory_text,
            memory_value_json=value,
            confidence=confidence,
            importance=importance,
            course_scope="course",
            source=f"rule:{signal}",
            evidence=evidence,
            utterance_type="semantic_inference",
        )

    @staticmethod
    def _extract_user_name(text: str) -> str | None:
        return agent_memory_semantics_service.extract_name_statement(text)

    @staticmethod
    def _extract_name_update(text: str) -> str | None:
        return agent_memory_semantics_service.extract_name_update(text)

    @staticmethod
    def _states_student_identity(text: str) -> bool:
        return any(token in text for token in ["我是学生", "我现在是学生", "我是一名学生"])

    @staticmethod
    def _prefers_name_in_reply(text: str) -> bool:
        reply_words = ["后面回答", "以后回答", "之后回答", "每次回答", "后续回答"]
        name_words = ["加上我的名字", "带上我的名字", "叫我的名字", "称呼我", "加上称呼", "带上称呼"]
        return any(word in text for word in reply_words) and any(word in text for word in name_words)

    def _extract_explicit_remember_requests(self, text: str) -> list[AgentMemoryCandidate]:
        candidates: list[AgentMemoryCandidate] = []
        for match in re.finditer(r"(?:记住|你要记住|帮我记住)\s*(?:：|:)?\s*([^。！？\n]{2,80})", text):
            content = match.group(1).strip(" ，。,.!！?？；;：:")
            if not content or any(token in content for token in ["名字", "我叫", "叫我"]):
                continue
            candidates.append(
                AgentMemoryCandidate(
                    memory_type="semantic",
                    memory_key=f"explicit:{self._stable_hash(content)}",
                    memory_text=f"用户明确要求记住：{content}。",
                    memory_value_json={"content": content},
                    confidence=0.9,
                    importance=0.7,
                    course_scope="global",
                    source="rule:explicit_remember",
                    evidence=match.group(0)[:200],
                    utterance_type="explicit_remember",
                )
            )
        return candidates

    def _extract_learning_preference(self, text: str) -> AgentMemoryCandidate | None:
        if not text or self._is_memory_recall_question(text):
            return None
        example_markers = ["例子", "举例", "案例"]
        preference_markers = ["喜欢", "更喜欢", "希望", "偏好", "习惯", "以后", "后面", "之后", "多用", "多举"]
        explain_markers = ["讲", "解释", "说明", "回答", "教"]
        if not any(marker in text for marker in example_markers):
            return None
        if not any(marker in text for marker in preference_markers):
            return None
        if not any(marker in text for marker in explain_markers):
            return None
        return AgentMemoryCandidate(
            memory_type="preference",
            memory_key="explain_with_examples",
            memory_text="用户偏好用简单例子解释知识点。",
            memory_value_json={"style": "examples", "preference": "explain_with_examples"},
            confidence=0.9,
            importance=0.8,
            course_scope="global",
            source="rule:learning_preference",
            evidence=text[:200],
            utterance_type="preference_instruction",
        )

    def _extract_self_reported_weakness(self, text: str) -> str | None:
        if not text or self._is_memory_recall_question(text):
            return None
        patterns = [
            r"(?:我)?(?:总是|一直|经常|老是)?(?:搞不懂|不懂|不会|不理解|没理解|卡在|卡住|掌握不好|掌握得不好|掌握不太好|掌握得不太好|掌握的不太好|不熟)\s*([^，。！？?]{2,40})",
            r"(?:我(?:的)?|我对)?\s*([^，。！？?]{2,40}?)(?:这个)?(?:知识点|概念|内容)?(?:掌握不好|掌握得不好|掌握不太好|掌握得不太好|掌握的不太好)",
            r"([^，。！？?]{2,40})(?:这个)?(?:知识点|概念|内容)?(?:我)?(?:总是|一直|经常|老是)?(?:搞不懂|不懂|不会|不理解|没理解|掌握不好|掌握得不好|掌握不太好|掌握得不太好|掌握的不太好|不熟|薄弱|卡住)",
            r"(?:薄弱点|弱点|短板)(?:是|在于|：|:)?\s*([^，。！？?]{2,40})",
            r"([^，。！？?]{2,40})(?:是)?(?:我的)?(?:薄弱点|弱点|短板)",
        ]
        return self._first_learning_topic_match(text, patterns)

    def _extract_self_reported_mastery(self, text: str, fallback_topic: str | None = None) -> str | None:
        if not text or self._is_memory_recall_question(text):
            return None
        mastery_markers = ["会了", "懂了", "理解了", "掌握了", "搞懂了", "学会了"]
        if not any(marker in text for marker in mastery_markers):
            return None
        patterns = [
            r"([^，。！？?]{2,40}?)(?:这个)?(?:知识点|概念|内容)?我(?:已经|现在|基本|差不多)?(?:会了|懂了|理解了|掌握了|搞懂了|学会了)",
            r"([^，。！？?]{2,40}?)(?:这个)?(?:知识点|概念|内容)?(?:已经|现在|基本|差不多)(?:会了|懂了|理解了|掌握了|搞懂了|学会了)",
            r"(?:我)(?:已经|现在|基本|差不多)?(?:会了|懂了|理解了|掌握了|搞懂了|学会了)\s*([^，。！？?]{2,40})",
        ]
        topic = self._first_learning_topic_match(text, patterns)
        if topic:
            return topic
        return self._clean_learning_topic(fallback_topic)

    def _extract_learning_goal(self, text: str) -> tuple[str, dict] | None:
        if not text or self._is_memory_recall_question(text):
            return None

        goal_text = None
        explicit = re.search(r"(?:我的)?(?:学习)?目标(?:是|：|:)\s*([^。！？\n]{2,80})", text)
        if explicit:
            goal_text = explicit.group(1)
        else:
            has_goal_intent = any(marker in text for marker in ["我要", "我想", "我希望", "计划", "打算"])
            has_goal_target = any(
                marker in text
                for marker in ["通过", "考过", "掌握", "学完", "达到", "提升", "期末", "考试", "四级", "两周", "天内", "周内", "月内"]
            )
            if has_goal_intent and has_goal_target:
                match = re.search(r"(?:我要|我想|我希望|计划|打算)\s*([^。！？\n]{2,80})", text)
                if match:
                    goal_text = match.group(1)

        if not goal_text:
            return None

        goal_text = goal_text.strip(" ，。,.!！?？；;：:")
        if not goal_text or len(goal_text) > 80:
            return None

        value = {"goal": goal_text}
        duration_days = self._extract_duration_days(text)
        if duration_days:
            value["duration_days"] = duration_days
        target_score = self._extract_target_score(text)
        if target_score is not None:
            value["target_score"] = target_score
        exam = self._extract_exam_name(text)
        if exam:
            value["exam"] = exam
        return goal_text, value

    def _extract_practice_weakness(self, tool_result: dict, response: dict, intent_result) -> tuple[str, int] | None:
        practice_result = (tool_result or {}).get("practice_result") or (response or {}).get("practice_result") or {}
        practice_session = (tool_result or {}).get("practice_session") or (response or {}).get("practice_session") or {}
        if practice_result.get("is_correct") is not False:
            return None

        wrong_count = practice_result.get("wrong_streak") or practice_session.get("wrong_streak")
        if wrong_count is None:
            answered_count = practice_session.get("answered_count")
            correct_count = practice_session.get("correct_count")
            if answered_count is not None and correct_count is not None:
                wrong_count = int(answered_count or 0) - int(correct_count or 0)
        wrong_count = int(wrong_count or 0)
        if wrong_count < 3:
            return None

        topic = (
            practice_session.get("topic")
            or practice_result.get("topic")
            or getattr(intent_result, "topic", None)
        )
        topic = self._clean_learning_topic(topic)
        if not topic:
            return None
        return topic, wrong_count

    def _first_learning_topic_match(self, text: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                topic = self._clean_learning_topic(match.group(1) if match.lastindex else None)
                if topic:
                    return topic
        return None

    @staticmethod
    def _clean_learning_topic(topic: str | None) -> str | None:
        value = (topic or "").strip(" “”，。,.!！?？；;：:\t\r\n")
        if not value:
            return None
        for prefix in ["我对", "我在", "关于", "这个", "那个", "做"]:
            if value.startswith(prefix):
                value = value[len(prefix):].strip(" “”，。,.!！?？；;：:")
        for suffix in ["这个知识点", "这个概念", "知识点", "概念", "内容", "这一块", "这块", "题", "练习"]:
            if value.endswith(suffix):
                value = value[: -len(suffix)].strip(" “”，。,.!！?？；;：:")
        invalid_topics = {"我", "我已经", "我现在", "已经", "现在", "这个", "那个", "这个知识点", "知识点", "概念", "内容", "它"}
        if value in invalid_topics or len(value) < 2 or len(value) > 50:
            return None
        if any(token in value for token in ["吗", "什么", "怎么", "为什么", "能不能"]):
            return None
        return value

    @staticmethod
    def _extract_duration_days(text: str) -> int | None:
        match = re.search(r"(\d+)\s*天", text)
        if match:
            return int(match.group(1))
        match = re.search(r"(\d+)\s*周", text)
        if match:
            return int(match.group(1)) * 7
        match = re.search(r"(\d+)\s*个?月", text)
        if match:
            return int(match.group(1)) * 30
        if "两周" in text:
            return 14
        if "一周" in text or "一个星期" in text:
            return 7
        if "一个月" in text:
            return 30
        if "两个月" in text:
            return 60
        return None

    @staticmethod
    def _extract_target_score(text: str) -> int | None:
        match = re.search(r"(\d+)\s*分", text)
        if not match:
            return None
        score = int(match.group(1))
        return score if 0 <= score <= 100 else None

    @staticmethod
    def _extract_exam_name(text: str) -> str | None:
        if "大学英语四级" in text:
            return "大学英语四级"
        if "英语四级" in text:
            return "英语四级"
        if "四级" in text:
            return "四级"
        match = re.search(r"([\u4e00-\u9fffA-Za-z0-9_]{2,20})(?:期末|考试)", text)
        if match:
            return match.group(1).strip()
        return None

    def _extract_learning_topic(
        self,
        db: Session,
        course_id: int,
        user_message: str,
        intent_result,
        tool_result: dict,
        response: dict,
    ) -> tuple[str, list[int]] | None:
        if self._is_memory_recall_question(user_message):
            return None

        topic = getattr(intent_result, "topic", None)
        related_ids = (
            response.get("related_knowledge_point_ids")
            or tool_result.get("related_knowledge_point_ids")
            or getattr(intent_result, "knowledge_point_ids", [])
            or []
        )
        related_ids = [int(item) for item in related_ids if item is not None]

        point_names = self._knowledge_point_names(db, related_ids)
        if not topic and point_names:
            topic = "、".join(point_names)
        if not topic:
            topic = self._extract_topic_from_question(user_message)
        if not topic:
            return None

        topic = topic.strip(" ，。,.!！?？；;：:")
        if not topic or len(topic) > 80:
            return None

        learning_tools = {
            "qa_answer",
            "continue_explanation",
            "provide_code_example",
            "provide_compare_explanation",
            "generate_inline_practice",
            "generate_exercise_document",
            "start_guided_practice",
        }
        tool_name = getattr(intent_result, "tool_name", None)
        if tool_name not in learning_tools and not related_ids:
            return None

        return topic, related_ids

    @staticmethod
    def _is_memory_recall_question(text: str) -> bool:
        return agent_memory_semantics_service.is_memory_recall_question(text)

    @staticmethod
    def _extract_topic_from_question(text: str) -> str | None:
        patterns = [
            r"(?:讲一下|解释一下|说一下|介绍一下|讲讲|解释解释)\s*([^，。！？?]{2,40})",
            r"(?:什么是|啥是)\s*([^，。！？?]{2,40})",
            r"([^，。！？?]{2,40})(?:是什么|怎么理解|有啥用|有什么用)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                topic = match.group(1).strip(" ，。,.!！?？；;：:吧呢吗")
                if topic:
                    return topic
        return None

    # ================================================================
    # Semantic extraction
    # ================================================================

    def _should_run_semantic_extractor(self, user_message: str, intent_result, response: dict) -> bool:
        text = user_message or ""
        if any(word in text for word in ["记住", "我叫", "我的名字", "以后", "后面", "偏好", "喜欢", "不喜欢"]):
            return True
        if response.get("related_knowledge_point_ids"):
            return True
        return getattr(intent_result, "tool_name", None) in {
            "qa_answer",
            "continue_explanation",
            "provide_code_example",
            "provide_compare_explanation",
            "generate_inline_practice",
            "grade_practice_answer",
        }

    def _extract_with_qwen_json(
        self,
        context: dict,
        user_message: str,
        intent_result,
        tool_result: dict,
        response: dict,
    ) -> list[AgentMemoryCandidate]:
        prompt = self._build_qwen_extraction_prompt(
            context=context,
            user_message=user_message,
            intent_result=intent_result,
            tool_result=tool_result,
            response=response,
        )
        raw = qwen_client.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是长期记忆抽取器，只输出严格 JSON 数组。"
                        "不要输出 Markdown，不要解释。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        parsed = self._parse_json_array(raw)
        return [AgentMemoryCandidate.model_validate(item) for item in parsed]

    def _extract_with_langmem(
        self,
        context: dict,
        user_message: str,
        response: dict,
    ) -> list[AgentMemoryCandidate]:
        from langchain_openai import ChatOpenAI
        from langmem import create_memory_manager

        llm = ChatOpenAI(
            model=settings.qwen_chat_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            temperature=0,
        )
        manager = create_memory_manager(
            llm,
            schemas=[AgentMemoryCandidate],
            instructions=(
                "从智慧学习 Agent 的一轮对话中抽取值得长期保留的记忆。"
                "只保留稳定事实、明确偏好、学习状态、用户问过的重要知识点。"
                "不要记录临时寒暄、无意义确认或模型自己编造的内容。"
            ),
            enable_deletes=False,
        )
        existing = self._existing_for_langmem(context)
        extracted = manager.invoke(
            {
                "messages": [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": response.get("text") or ""},
                ],
                "existing": existing,
                "max_steps": 1,
            }
        )
        candidates: list[AgentMemoryCandidate] = []
        for item in extracted:
            content = getattr(item, "content", None)
            if isinstance(content, AgentMemoryCandidate):
                candidate = content
            elif hasattr(content, "model_dump"):
                candidate = AgentMemoryCandidate.model_validate(content.model_dump())
            else:
                continue
            candidate.source = "langmem"
            candidates.append(candidate)
        return candidates

    @staticmethod
    def _existing_for_langmem(context: dict) -> list[tuple[str, AgentMemoryCandidate]]:
        memory_context = context.get("long_term_memory") or {}
        existing: list[tuple[str, AgentMemoryCandidate]] = []
        for key in [
            "profile_memories",
            "preference_memories",
            "learning_state_memories",
            "episodic_memories",
            "semantic_memories",
            "procedural_memories",
        ]:
            for memory in memory_context.get(key) or []:
                existing.append(
                    (
                        str(memory.id),
                        AgentMemoryCandidate(
                            memory_type=memory.memory_type,
                            memory_key=memory.memory_key,
                            memory_text=memory.memory_text,
                            memory_value_json=memory.memory_value_json,
                            confidence=memory.confidence or 0.8,
                            importance=memory.importance or 0.5,
                            course_scope="global" if memory.course_id is None else "course",
                            source="existing",
                        ),
                    )
                )
        return existing

    def _build_qwen_extraction_prompt(
        self,
        context: dict,
        user_message: str,
        intent_result,
        tool_result: dict,
        response: dict,
    ) -> str:
        memory_context_text = (context.get("memory_context_text") or "")[:2000]
        tool_text = (tool_result.get("text") or "")[:1000]
        response_text = (response.get("text") or "")[:1000]
        intent_json = json.dumps(
            intent_result.model_dump() if hasattr(intent_result, "model_dump") else {},
            ensure_ascii=False,
            default=str,
        )
        return f"""
请从下面这一轮学习 Agent 对话中抽取长期记忆候选。

只抽取这些内容：
1. 用户画像：姓名、身份、长期目标等稳定事实。
2. 用户偏好：希望如何被称呼、回答风格偏好、学习方式偏好。
3. 学习状态：明显薄弱点、正在学习的主题、掌握情况。
4. 历史事件：用户问过的重要知识点或完成过的重要学习动作。
5. 语义总结：用户明确要求记住的事实。
6. 回答策略：以后应该如何更好地服务该用户。

不要抽取：
- 临时寒暄。
- 模型自己猜测但用户没表达的信息。
- 与学习或个性化服务无关的碎片。
- 已有记忆中完全重复且没有增强的信息。

输出 JSON 数组，每项必须是：
{{
  "memory_type": "profile|preference|learning_state|episodic|semantic|procedural",
  "memory_key": "稳定短 key，128 字符以内",
  "memory_text": "独立可读的一句话记忆",
  "memory_value_json": {{}},
  "confidence": 0.0,
  "importance": 0.0,
  "course_scope": "global|course",
  "source": "llm",
  "evidence": "支持这条记忆的用户原文片段",
  "utterance_type": "self_statement|preference_instruction|learning_question|explicit_remember|memory_recall|semantic_inference|unknown",
  "action": "upsert"
}}

全局记忆用于姓名、身份、回答偏好；课程记忆用于某门课下的问题、薄弱点、知识点事件。
如果没有值得长期记住的信息，输出 []。

【已有长期记忆】
{memory_context_text or "无"}

【用户输入】
{user_message}

【意图结果】
{intent_json}

【工具结果摘要】
{tool_text}

【最终回答摘要】
{response_text}
"""

    # ================================================================
    # Normalization helpers
    # ================================================================

    def _normalize_candidates(self, candidates: list[AgentMemoryCandidate]) -> list[AgentMemoryCandidate]:
        normalized: list[AgentMemoryCandidate] = []
        for candidate in candidates:
            if candidate.memory_type not in VALID_MEMORY_TYPES:
                continue
            candidate.memory_key = candidate.memory_key.strip()[:128]
            candidate.memory_text = candidate.memory_text.strip()
            if not candidate.memory_key or not candidate.memory_text:
                continue
            candidate.confidence = self._clamp(candidate.confidence)
            candidate.importance = self._clamp(candidate.importance)
            candidate.evidence = (candidate.evidence or "").strip()[:500] or None
            candidate.utterance_type = (candidate.utterance_type or "unknown").strip()
            candidate.action = (candidate.action or "upsert").strip()
            if candidate.memory_type in {"profile", "preference", "procedural"}:
                candidate.course_scope = "global"
            normalized.append(candidate)
        return normalized

    @staticmethod
    def _dedupe_candidates(candidates: list[AgentMemoryCandidate]) -> list[AgentMemoryCandidate]:
        by_key: dict[tuple[str, str, str], AgentMemoryCandidate] = {}
        for candidate in candidates:
            key = (candidate.course_scope, candidate.memory_type, candidate.memory_key)
            current = by_key.get(key)
            if not current:
                by_key[key] = candidate
                continue
            current_score = (current.importance or 0) + (current.confidence or 0)
            candidate_score = (candidate.importance or 0) + (candidate.confidence or 0)
            if candidate_score >= current_score:
                by_key[key] = candidate
        return sorted(
            by_key.values(),
            key=lambda item: (item.importance or 0, item.confidence or 0),
            reverse=True,
        )

    @staticmethod
    def _parse_json_array(text: str) -> list:
        text = (text or "").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, list):
            raise ValueError("memory extraction output must be a JSON array")
        return parsed

    @staticmethod
    def _knowledge_point_names(db: Session, ids: list[int]) -> list[str]:
        if not ids:
            return []
        points = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(ids)).all()
        return [point.name for point in points]

    @staticmethod
    def _short_key(text: str) -> str:
        text = re.sub(r"\s+", "_", (text or "").strip())
        if len(text) <= 64:
            return text
        return text[:48] + "_" + AgentMemoryExtractionService._stable_hash(text)[:10]

    @staticmethod
    def _stable_hash(text: str) -> str:
        return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _extract_name_evidence(text: str, name: str) -> str:
        return agent_memory_semantics_service.extract_name_evidence(text, name)

    @staticmethod
    def _matched_text(text: str, markers: list[str]) -> str | None:
        for marker in markers:
            if marker in text:
                return marker
        return text[:200] if text else None

    @staticmethod
    def _clamp(value: float | int | None) -> float:
        if value is None:
            return 0.0
        return max(0.0, min(float(value), 1.0))


agent_memory_extraction_service = AgentMemoryExtractionService()
