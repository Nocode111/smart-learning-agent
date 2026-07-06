"""
Memory write policy service.

This layer decides whether extracted memory candidates are safe to write.
It protects high-value memories from being overwritten by recall questions,
low-confidence guesses, and weak evidence.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.agent_long_term_memory_service import agent_long_term_memory_service
from app.services.agent_memory_semantics_service import agent_memory_semantics_service

PolicyAction = Literal["create", "update", "reinforce", "reject"]


class MemoryWriteDecision(BaseModel):
    allow: bool
    action: PolicyAction
    reason: str
    existing_memory_id: int | None = None


class AgentMemoryWritePolicyService:
    protected_keys = {
        ("profile", "name"),
        ("profile", "role"),
    }

    allowed_utterance_types_by_memory_type = {
        "profile": {"self_statement", "explicit_remember", "correction"},
        "preference": {"preference_instruction", "explicit_remember", "correction"},
        "learning_state": {"learning_question", "semantic_inference", "correction"},
        "episodic": {"learning_question", "explicit_remember", "semantic_inference"},
        "semantic": {"explicit_remember", "semantic_inference", "self_statement"},
        "procedural": {"preference_instruction", "semantic_inference", "explicit_remember"},
    }

    def evaluate(
        self,
        db: Session,
        student_id: int,
        course_id: int | None,
        candidate,
        user_message: str,
        intent_result,
        context: dict | None = None,
    ) -> MemoryWriteDecision:
        text = (user_message or "").strip()
        if self._is_memory_recall_question(text):
            return MemoryWriteDecision(
                allow=False,
                action="reject",
                reason="memory_recall_question_is_read_only",
            )

        if candidate.action not in {"upsert", "create", "update", "reinforce"}:
            return MemoryWriteDecision(
                allow=False,
                action="reject",
                reason=f"unsupported_candidate_action:{candidate.action}",
            )

        if candidate.confidence < 0.55:
            return MemoryWriteDecision(
                allow=False,
                action="reject",
                reason="candidate_confidence_too_low",
            )

        allowed_types = self.allowed_utterance_types_by_memory_type.get(candidate.memory_type, set())
        if allowed_types and candidate.utterance_type not in allowed_types:
            return MemoryWriteDecision(
                allow=False,
                action="reject",
                reason=f"utterance_type_not_allowed:{candidate.utterance_type}",
            )

        evidence = candidate.evidence or text
        if not self._has_valid_evidence(candidate, evidence):
            return MemoryWriteDecision(
                allow=False,
                action="reject",
                reason="candidate_evidence_invalid_or_missing",
            )

        existing = agent_long_term_memory_service.find_active_memory_by_key(
            db=db,
            student_id=student_id,
            course_id=course_id,
            memory_type=candidate.memory_type,
            memory_key=candidate.memory_key,
        )

        if not existing:
            return MemoryWriteDecision(
                allow=True,
                action="create",
                reason="new_memory_allowed",
            )

        if self._same_memory(existing.memory_value_json, candidate.memory_value_json, existing.memory_text, candidate.memory_text):
            return MemoryWriteDecision(
                allow=True,
                action="reinforce",
                reason="same_memory_reinforced",
                existing_memory_id=existing.id,
            )

        if (candidate.memory_type, candidate.memory_key) in self.protected_keys:
            if not self._allows_protected_overwrite(candidate, text):
                return MemoryWriteDecision(
                    allow=False,
                    action="reject",
                    reason="protected_memory_overwrite_requires_explicit_correction",
                    existing_memory_id=existing.id,
                )

        if candidate.confidence < max(0.7, (existing.confidence or 0.0)):
            return MemoryWriteDecision(
                allow=False,
                action="reject",
                reason="candidate_confidence_not_enough_to_update_existing",
                existing_memory_id=existing.id,
            )

        return MemoryWriteDecision(
            allow=True,
            action="update",
            reason="existing_memory_update_allowed",
            existing_memory_id=existing.id,
        )

    def _has_valid_evidence(self, candidate, evidence: str) -> bool:
        evidence = (evidence or "").strip()
        if not evidence:
            return False

        if candidate.memory_type == "profile" and candidate.memory_key == "name":
            name = self._value(candidate.memory_value_json, "name")
            return bool(name) and self._is_valid_name_value(name) and self._name_evidence_supports_value(
                evidence,
                name,
                utterance_type=candidate.utterance_type,
            )

        if candidate.memory_type == "profile" and candidate.memory_key == "role":
            role = self._value(candidate.memory_value_json, "role")
            return role == "student" and any(token in evidence for token in ["我是学生", "我现在是学生", "我是一名学生"])

        if candidate.memory_type == "preference":
            return not self._is_question(evidence)

        if candidate.memory_type == "episodic":
            return candidate.utterance_type in {"learning_question", "explicit_remember", "semantic_inference"}

        return True

    @staticmethod
    def _allows_protected_overwrite(candidate, text: str) -> bool:
        evidence = candidate.evidence or text or ""
        if candidate.memory_type == "profile" and candidate.memory_key == "name":
            name = AgentMemoryWritePolicyService._value(candidate.memory_value_json, "name")
            if not AgentMemoryWritePolicyService._is_valid_name_value(name):
                return False
            correction_patterns = [
                r"我(?:现在)?(?:改名|改名字)了",
                r"以后叫我",
                r"以后称呼我",
                r"我不叫.+我叫",
                r"不是.+我叫",
            ]
            if any(re.search(pattern, evidence) for pattern in correction_patterns):
                return True
            return candidate.utterance_type in {"self_statement", "explicit_remember", "correction"} and AgentMemoryWritePolicyService._name_evidence_supports_value(
                evidence,
                name,
                utterance_type=candidate.utterance_type,
            )

        return candidate.utterance_type in {"correction", "explicit_remember", "self_statement"}

    @staticmethod
    def _same_memory(old_value: Any, new_value: Any, old_text: str, new_text: str) -> bool:
        return old_value == new_value or (old_text or "").strip() == (new_text or "").strip()

    @staticmethod
    def _value(value_json: Any, key: str):
        if isinstance(value_json, dict):
            return value_json.get(key)
        return None

    @staticmethod
    def _is_memory_recall_question(text: str) -> bool:
        return agent_memory_semantics_service.is_memory_recall_question(text)

    @staticmethod
    def _is_question(text: str) -> bool:
        return agent_memory_semantics_service.is_question(text)

    @staticmethod
    def _is_valid_name_value(name: str | None) -> bool:
        return agent_memory_semantics_service.is_valid_name_value(name)

    @staticmethod
    def _name_evidence_supports_value(evidence: str, name: str | None, utterance_type: str = "unknown") -> bool:
        return agent_memory_semantics_service.name_evidence_supports_value(evidence, name, utterance_type)


agent_memory_write_policy_service = AgentMemoryWritePolicyService()
