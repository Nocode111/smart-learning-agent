"""Policy layer for long-term memory recall.

This service decides which memory categories are allowed for a recall question
and ranks only the relevant records. It keeps retrieval rules out of the tool
executor so new recall patterns can be handled by category instead of by one
off patches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


MEMORY_TYPES = ["profile", "preference", "learning_state", "episodic", "semantic", "procedural"]


@dataclass(frozen=True)
class MemoryRecallPlan:
    category: str
    memory_types: list[str]
    excluded_memory_types: list[str] = field(default_factory=list)
    required_keys: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    include_learning_profile: bool = False
    include_graphiti: bool = False
    max_results: int = 5
    answer_style: str = "general"
    reason: str = ""


@dataclass
class RecallMemoryItem:
    memory_type: str
    memory_key: str
    memory_text: str
    memory_value_json: Any = None
    confidence: float = 0.0
    importance: float = 0.0
    source: str = "memory_table"
    score: float = 0.0
    raw: Any = None


class AgentMemoryRecallPolicyService:
    def build_plan(self, user_message: str, context: dict | None = None) -> MemoryRecallPlan:
        text = (user_message or "").strip()
        keywords = self._extract_query_terms(text)

        if self._is_identity_name_question(text):
            return MemoryRecallPlan(
                category="identity_name",
                memory_types=["profile"],
                excluded_memory_types=["learning_state", "episodic", "semantic", "procedural"],
                required_keys=["name"],
                keywords=keywords + ["名字", "叫什么"],
                include_graphiti=False,
                max_results=3,
                answer_style="name",
                reason="user asks for identity/name memory",
            )

        if self._is_learning_weakness_question(text):
            return MemoryRecallPlan(
                category="learning_weakness",
                memory_types=["learning_state", "episodic", "semantic"],
                excluded_memory_types=["profile", "preference"],
                keywords=keywords + ["知识点", "掌握", "薄弱", "弱点", "不会", "不熟", "不好", "不太好"],
                include_learning_profile=True,
                include_graphiti=True,
                max_results=5,
                answer_style="learning_weakness",
                reason="user asks for weak or poorly mastered learning memories",
            )

        if self._is_recent_learning_topic_question(text):
            return MemoryRecallPlan(
                category="recent_learning_topic",
                memory_types=["episodic", "learning_state", "semantic"],
                excluded_memory_types=["profile", "preference"],
                required_keys=["last_asked_topic", "recent_learning_topic"],
                keywords=keywords + ["知识点", "刚刚", "刚才", "问过", "说过", "学习"],
                include_learning_profile=True,
                include_graphiti=True,
                max_results=5,
                answer_style="recent_learning_topic",
                reason="user asks what learning topic was mentioned recently",
            )

        if self._is_goal_question(text):
            return MemoryRecallPlan(
                category="learning_goal",
                memory_types=["learning_state", "episodic", "semantic"],
                excluded_memory_types=["profile"],
                keywords=keywords + ["目标", "计划", "学习目标", "安排"],
                include_learning_profile=True,
                include_graphiti=True,
                max_results=5,
                answer_style="learning_goal",
                reason="user asks for learning goals or plans",
            )

        if self._is_preference_question(text):
            return MemoryRecallPlan(
                category="preference",
                memory_types=["preference", "procedural"],
                excluded_memory_types=["profile"],
                keywords=keywords + ["喜欢", "偏好", "习惯", "方式", "怎么回答"],
                include_graphiti=False,
                max_results=5,
                answer_style="preference",
                reason="user asks for preference memory",
            )

        return MemoryRecallPlan(
            category="general",
            memory_types=MEMORY_TYPES,
            keywords=keywords,
            include_learning_profile=True,
            include_graphiti=True,
            max_results=5,
            answer_style="general",
            reason="general memory recall",
        )

    def select_memories(self, context: dict | None, plan: MemoryRecallPlan) -> list[RecallMemoryItem]:
        context = context or {}
        candidates = self._collect_candidates(context, plan)
        if not candidates:
            return []

        scored = []
        for item in candidates:
            item.score = self._score_item(item, plan)
            if item.score > 0:
                scored.append(item)

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, plan.max_results)]

    def _collect_candidates(self, context: dict, plan: MemoryRecallPlan) -> list[RecallMemoryItem]:
        items: list[RecallMemoryItem] = []
        memory_context = context.get("long_term_memory") or {}
        allowed = set(plan.memory_types)
        excluded = set(plan.excluded_memory_types)

        for memory_type in MEMORY_TYPES:
            if memory_type in excluded or memory_type not in allowed:
                continue
            for memory in memory_context.get(f"{memory_type}_memories") or []:
                items.append(
                    RecallMemoryItem(
                        memory_type=memory_type,
                        memory_key=str(self._memory_attr(memory, "memory_key", "") or ""),
                        memory_text=str(self._memory_attr(memory, "memory_text", "") or ""),
                        memory_value_json=self._memory_attr(memory, "memory_value_json", None),
                        confidence=float(self._memory_attr(memory, "confidence", 0.0) or 0.0),
                        importance=float(self._memory_attr(memory, "importance", 0.0) or 0.0),
                        source="memory_table",
                        raw=memory,
                    )
                )

        if plan.include_learning_profile:
            profile_text = context.get("learning_profile_memory_context_text") or ""
            if profile_text:
                items.append(
                    RecallMemoryItem(
                        memory_type="learning_profile",
                        memory_key="learning_profile_context",
                        memory_text=profile_text,
                        confidence=0.7,
                        importance=0.7,
                        source="learning_profile",
                        raw=profile_text,
                    )
                )

        if plan.include_graphiti:
            graphiti = context.get("graphiti_memory") or {}
            for index, fact in enumerate(graphiti.get("facts") or []):
                fact_text = str(fact.get("fact") or fact.get("name") or "")
                if not fact_text:
                    continue
                items.append(
                    RecallMemoryItem(
                        memory_type="graphiti",
                        memory_key=str(fact.get("name") or f"graphiti_fact_{index}"),
                        memory_text=fact_text,
                        memory_value_json=fact,
                        confidence=0.65,
                        importance=0.65,
                        source="graphiti",
                        raw=fact,
                    )
                )

        return items

    def _score_item(self, item: RecallMemoryItem, plan: MemoryRecallPlan) -> float:
        haystack = self._item_haystack(item)
        score = item.importance + item.confidence

        if item.memory_type in plan.memory_types:
            score += 2.0
        if item.memory_type in plan.excluded_memory_types:
            return 0.0
        if plan.required_keys and any(key in item.memory_key for key in plan.required_keys):
            score += 5.0

        for keyword in plan.keywords:
            if keyword and keyword.lower() in haystack:
                score += 2.0

        if plan.category == "identity_name":
            if item.memory_type == "profile" and ("name" in item.memory_key or "名字" in haystack):
                score += 6.0
            else:
                return 0.0

        if plan.category in {"learning_weakness", "recent_learning_topic", "learning_goal"}:
            learning_terms = ["知识点", "学习", "掌握", "薄弱", "弱点", "不会", "不熟", "课程", "目标", "计划"]
            if any(term in haystack for term in learning_terms):
                score += 4.0
            if item.memory_type in {"profile", "preference"}:
                return 0.0

        if plan.category == "preference" and item.memory_type not in {"preference", "procedural"}:
            return 0.0

        return score

    @staticmethod
    def _item_haystack(item: RecallMemoryItem) -> str:
        return f"{item.memory_type} {item.memory_key} {item.memory_text} {item.memory_value_json}".lower()

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
            "之前",
        }
        return [term for term in terms if term not in stop_words]

    @staticmethod
    def _is_identity_name_question(text: str) -> bool:
        return any(term in text for term in ["叫什么", "名字", "怎么称呼"]) and any(
            term in text for term in ["记得", "还记得", "我叫", "我的"]
        )

    @staticmethod
    def _is_learning_weakness_question(text: str) -> bool:
        learning = any(term in text for term in ["知识点", "学习", "课程", "概念", "内容"])
        weakness = any(
            term in text
            for term in [
                "掌握不好",
                "掌握得不好",
                "掌握不太好",
                "掌握得不太好",
                "掌握的不太好",
                "不太好",
                "不好",
                "薄弱",
                "弱点",
                "不会",
                "不熟",
                "卡住",
            ]
        )
        recall = any(term in text for term in ["记得", "刚刚", "刚才", "之前", "最近", "哪个", "什么"])
        implicit_learning = any(term in text for term in ["哪个掌握", "哪个不太好", "哪个不好"])
        return (learning or implicit_learning) and weakness and recall

    @staticmethod
    def _is_recent_learning_topic_question(text: str) -> bool:
        topic = any(term in text for term in ["知识点", "主题", "概念", "内容", "问题"])
        recent = any(term in text for term in ["刚刚", "刚才", "之前", "上次", "最近"])
        action = any(term in text for term in ["问", "说", "提到", "学", "讲"])
        return topic and recent and action

    @staticmethod
    def _is_goal_question(text: str) -> bool:
        return any(term in text for term in ["目标", "计划", "安排"]) and any(
            term in text for term in ["记得", "之前", "最近", "我的"]
        )

    @staticmethod
    def _is_preference_question(text: str) -> bool:
        return any(term in text for term in ["偏好", "喜欢", "习惯", "回答方式", "学习方式"]) and any(
            term in text for term in ["记得", "之前", "我的", "我"]
        )


agent_memory_recall_policy_service = AgentMemoryRecallPolicyService()
