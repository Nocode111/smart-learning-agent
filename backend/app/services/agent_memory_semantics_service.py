"""
Deterministic memory semantics used by routing, extraction, policy, and evals.

This module keeps high-confidence text judgments in one place so memory
behavior does not drift across RuleGate, extraction, and write policy.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NameMention:
    value: str
    evidence: str
    utterance_type: str
    action: str


class AgentMemorySemanticsService:
    question_markers = ("?", "？", "吗", "么", "什么", "谁", "多少")
    invalid_name_tokens = ("什么", "名字", "吗", "呢", "谁", "多少", "记得", "叫")

    name_update_patterns = (
        r"(?:改名|改名字|换名|换名字)了?[，,。\s]*(?:以后|之后)?(?:叫我|称呼我|我是|我叫)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})(?=[，。,.!！?？；;：:\s]|$)",
        r"(?:以后|之后|从现在开始)(?:叫我|称呼我)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})(?=[，。,.!！?？；;：:\s]|$)",
        r"我不叫.+?(?:我叫|叫我|我是)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})(?=[，。,.!！?？；;：:\s]|$)",
        r"不是.+?(?:我叫|叫我|我是)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})(?=[，。,.!！?？；;：:\s]|$)",
        r"(?:别叫我|不要叫我).+?(?:叫我|我叫|我是)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})(?=[，。,.!！?？；;：:\s]|$)",
    )

    name_statement_patterns = (
        r"(?:我的名字(?:叫|是)|我叫|叫我)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,20})(?=[，。,.!！?？；;：:\s]|$)",
    )

    recall_targets = (
        "我叫什么",
        "我的名字",
        "刚刚问",
        "刚才问",
        "刚刚说",
        "刚才说",
        "哪个知识点",
        "什么知识点",
        "哪个掌握",
        "掌握不好",
        "掌握得不好",
        "掌握不太好",
        "掌握得不太好",
        "掌握的不太好",
        "问了什么",
    )

    name_recall_targets = ("我叫什么", "我的名字", "名字")
    topic_recall_targets = (
        "刚刚问",
        "刚才问",
        "刚刚说",
        "刚才说",
        "哪个知识点",
        "什么知识点",
        "哪个掌握",
        "掌握不好",
        "掌握不太好",
        "掌握的不太好",
        "问了什么",
    )

    def classify_name_mention(self, text: str) -> NameMention | None:
        normalized = self.normalize_text(text)
        if not normalized or self.is_memory_recall_question(normalized):
            return None

        update = self.extract_name_update(normalized)
        if update:
            return NameMention(
                value=update,
                evidence=normalized[:200],
                utterance_type="correction",
                action="update",
            )

        stated = self.extract_name_statement(normalized)
        if stated:
            return NameMention(
                value=stated,
                evidence=self.extract_name_evidence(normalized, stated),
                utterance_type="self_statement",
                action="upsert",
            )

        return None

    def extract_name_update(self, text: str) -> str | None:
        return self._first_valid_name(self.normalize_text(text), self.name_update_patterns)

    def extract_name_statement(self, text: str) -> str | None:
        return self._first_valid_name(self.normalize_text(text), self.name_statement_patterns, last=True)

    def is_memory_recall_question(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        if not normalized:
            return False
        if "记得" in normalized and any(target in normalized for target in self.recall_targets):
            return True
        return any(phrase in normalized for phrase in ["我刚才问了什么", "我刚刚问了什么"])

    def is_name_recall_question(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        return self.is_memory_recall_question(normalized) and any(target in normalized for target in self.name_recall_targets)

    def is_topic_recall_question(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        return self.is_memory_recall_question(normalized) and any(target in normalized for target in self.topic_recall_targets)

    def is_question(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        return any(marker in normalized for marker in self.question_markers)

    def is_valid_name_value(self, name: str | None) -> bool:
        if not name:
            return False
        value = name.strip()
        if not (1 <= len(value) <= 20):
            return False
        return not any(token in value for token in self.invalid_name_tokens)

    def name_evidence_supports_value(self, evidence: str, name: str | None, utterance_type: str = "unknown") -> bool:
        if not self.is_valid_name_value(name):
            return False
        normalized = self.normalize_text(evidence)
        if self.is_question(normalized):
            return False

        value = name.strip()
        if utterance_type == "correction":
            correction_markers = ("改名", "改名字", "换名", "换名字", "以后叫我", "以后称呼我", "我不叫", "不是", "别叫我", "不要叫我")
            return value in normalized and any(marker in normalized for marker in correction_markers)

        return any(
            marker in normalized
            for marker in [
                f"我叫{value}",
                f"我的名字叫{value}",
                f"我的名字是{value}",
                f"叫我{value}",
                f"以后叫我{value}",
                f"以后称呼我{value}",
            ]
        )

    def extract_name_evidence(self, text: str, name: str) -> str:
        normalized = self.normalize_text(text)
        value = (name or "").strip()
        if not value:
            return normalized[:200]

        markers = [
            f"我叫{value}",
            f"我的名字叫{value}",
            f"我的名字是{value}",
            f"叫我{value}",
            f"称呼我{value}",
            f"我是{value}",
            f"以后叫我{value}",
            f"以后称呼我{value}",
        ]
        for marker in markers:
            if marker in normalized:
                return marker
        return normalized[:200]

    def _first_valid_name(self, text: str, patterns: tuple[str, ...], last: bool = False) -> str | None:
        names: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1).strip(" ，。,.!！?？；;：:")
                if self.is_valid_name_value(name):
                    names.append(name)
        if not names:
            return None
        return names[-1] if last else names[0]

    @staticmethod
    def normalize_text(text: str | None) -> str:
        return re.sub(r"\s+", "", (text or "").strip())


agent_memory_semantics_service = AgentMemorySemanticsService()
