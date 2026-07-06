"""Answer composer for memory recall results."""

from __future__ import annotations

import re
from typing import Any

from app.services.agent_memory_recall_policy_service import MemoryRecallPlan, RecallMemoryItem
from app.services.agent_memory_semantics_service import agent_memory_semantics_service


class AgentMemoryAnswerComposerService:
    def compose(
        self,
        plan: MemoryRecallPlan,
        memories: list[RecallMemoryItem],
        context: dict | None,
        user_message: str,
    ) -> dict:
        context = context or {}
        if plan.answer_style == "name":
            text = self._compose_name_answer(memories, context)
        elif plan.answer_style in {"learning_weakness", "recent_learning_topic"}:
            text = self._compose_learning_answer(plan, memories, context, user_message)
        elif plan.answer_style == "learning_goal":
            text = self._compose_list_answer(memories, "我查到你之前提到的学习目标或计划是：")
        elif plan.answer_style == "preference":
            text = self._compose_list_answer(memories, "我查到你之前提到的偏好是：")
        else:
            text = self._compose_general_answer(memories)

        return {
            "text": text,
            "category": plan.category,
            "selected_count": len(memories),
            "selected_memory_types": self._dedupe([item.memory_type for item in memories]),
        }

    def _compose_name_answer(self, memories: list[RecallMemoryItem], context: dict) -> str:
        for item in memories:
            name = self._extract_name(item)
            if name:
                return f"我记得，你叫{name}。"

        recent_name = self._find_recent_user_name(context)
        if recent_name:
            return f"我记得，你叫{recent_name}。"
        return "我现在还没有从长期记忆里找到你的名字。"

    def _compose_learning_answer(
        self,
        plan: MemoryRecallPlan,
        memories: list[RecallMemoryItem],
        context: dict,
        user_message: str,
    ) -> str:
        topics = []
        raw_lines = []
        for item in memories:
            topic = self._extract_learning_topic(item)
            if topic:
                topics.append(topic)
            elif item.memory_text:
                raw_lines.append(self._clean_memory_text(item.memory_text))

        if not topics:
            context_topic = context.get("last_topic")
            if context_topic:
                topics.append(str(context_topic))

        topics = self._dedupe([topic for topic in topics if topic])
        raw_lines = self._dedupe([line for line in raw_lines if line])

        if topics:
            joined = "、".join(topics[:3])
            if plan.answer_style == "learning_weakness" or any(
                term in user_message for term in ["不好", "薄弱", "不会", "不熟", "卡住", "弱点"]
            ):
                return f"我查到你提到掌握得不太好的知识点是：{joined}。"
            return f"我查到你最近提到的学习知识点是：{joined}。"

        if raw_lines:
            return "我查到和你这个问题相关的学习记忆是：\n" + "\n".join(f"- {line}" for line in raw_lines[:3])

        if plan.answer_style == "learning_weakness":
            return "我现在还没有查到你之前明确说过哪个知识点掌握得不好。"
        return "我现在还没有找到上一轮明确的知识点记录。"

    def _compose_list_answer(self, memories: list[RecallMemoryItem], prefix: str) -> str:
        lines = self._dedupe([self._clean_memory_text(item.memory_text) for item in memories if item.memory_text])
        if not lines:
            return "我现在还没有查到和这个问题直接相关的长期记忆。"
        return prefix + "\n" + "\n".join(f"- {line}" for line in lines[:5])

    def _compose_general_answer(self, memories: list[RecallMemoryItem]) -> str:
        lines = self._dedupe([self._clean_memory_text(item.memory_text) for item in memories if item.memory_text])
        if not lines:
            return "我现在还没有查到和这个问题直接相关的长期记忆。"
        return "我查到的相关长期记忆是：\n" + "\n".join(f"- {line}" for line in lines[:5])

    @staticmethod
    def _extract_name(item: RecallMemoryItem) -> str | None:
        value = item.memory_value_json
        if isinstance(value, dict) and value.get("name"):
            return str(value["name"])

        for pattern in [
            r"名字是([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})",
            r"叫([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})",
        ]:
            match = re.search(pattern, item.memory_text or "")
            if match:
                return match.group(1).strip(" ，。；;！？")
        return None

    @staticmethod
    def _extract_learning_topic(item: RecallMemoryItem) -> str | None:
        value = item.memory_value_json
        if isinstance(value, dict):
            for key in ["topic", "knowledge_point", "knowledge_point_name", "weak_point", "name"]:
                if value.get(key):
                    return str(value[key])
            for key in ["topics", "knowledge_points", "weak_points"]:
                items = value.get(key)
                if isinstance(items, list) and items:
                    return "、".join(str(entry) for entry in items[:3])

        text = item.memory_text or ""
        for pattern in [
            r"知识点是[“\"]?([^”\"，。；;！？\s]{2,40})",
            r"知识点[：:]?[“\"]([^”\"]{2,40})[”\"]",
            r"[“\"]([^”\"]{2,40})[”\"]这个知识点",
            r"(?:说|提到|问过|学习|学过)([^，。；;！？\s]{2,40})这个知识点",
            r"([^，。；;！？\s]{2,40})这个知识点(?:掌握|学得|理解)",
        ]:
            match = re.search(pattern, text)
            if match:
                topic = match.group(1).strip(" “”，。；;！？")
                return self_trim_topic(topic)
        return None

    @staticmethod
    def _clean_memory_text(text: str) -> str:
        value = (text or "").strip()
        value = re.sub(r"^【[^】]+】\s*", "", value)
        return value

    @staticmethod
    def _find_recent_user_name(context: dict) -> str | None:
        recent_messages = context.get("recent_messages") or []
        for item in reversed(recent_messages):
            if item.get("role") != "user":
                continue
            mention = agent_memory_semantics_service.classify_name_mention(item.get("content") or "")
            if mention:
                return mention.value
        return None

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(key)
        return result


def self_trim_topic(topic: str) -> str:
    for prefix in ["用户最近说", "用户最近问过", "用户问过", "用户说", "我最近说", "我刚刚说", "我说"]:
        if topic.startswith(prefix):
            return topic[len(prefix):].strip(" ：:，。；;！？")
    return topic


agent_memory_answer_composer_service = AgentMemoryAnswerComposerService()
