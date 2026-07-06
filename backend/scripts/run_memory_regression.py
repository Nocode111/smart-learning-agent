"""Run deterministic long-term memory regression checks.

Usage:
    python scripts/run_memory_regression.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.evals.memory_regression_cases import MEMORY_REGRESSION_CASES
from app.models.agent_memory import AgentMemory, AgentMemoryEvent
from app.config import settings
from app.services.agent_long_term_memory_service import agent_long_term_memory_service
from app.services.agent_memory_extraction_service import agent_memory_extraction_service
from app.services.agent_memory_recall_policy_service import agent_memory_recall_policy_service
from app.services.agent_rule_gate_service import agent_rule_gate_service
from app.services.llm_intent_router_service import IntentRouterResult


@dataclass
class MemoryRegressionFailure:
    case_id: str
    detail: str


class MemoryRegressionRunner:
    student_id = 987650001
    course_id = 1

    def __init__(self):
        self.failures: list[MemoryRegressionFailure] = []

    def run(self) -> int:
        original_use_llm = settings.agent_memory_extract_use_llm
        settings.agent_memory_extract_use_llm = False
        db = SessionLocal()
        try:
            for case in MEMORY_REGRESSION_CASES:
                self._run_case(db, case)
        finally:
            settings.agent_memory_extract_use_llm = original_use_llm
            self._cleanup(db)
            db.commit()
            db.close()

        total = len(MEMORY_REGRESSION_CASES)
        passed = total - len(self.failures)
        print(f"memory regression: {passed}/{total} passed")
        if self.failures:
            for failure in self.failures:
                print(f"[FAIL] {failure.case_id}: {failure.detail}")
            return 1
        return 0

    def _run_case(self, db, case: dict) -> None:
        self._cleanup(db)
        db.commit()

        seed_name = case.get("seed_name")
        if seed_name:
            agent_long_term_memory_service.create_memory(
                db=db,
                student_id=self.student_id,
                course_id=None,
                memory_type="profile",
                memory_key="name",
                memory_text=f"用户的名字是{seed_name}。",
                memory_value_json={"name": seed_name},
                confidence=0.95,
                importance=0.9,
                source_type="memory_regression_seed",
                reason="memory_regression_seed",
            )
            db.commit()

        message = case["message"]
        rule = agent_rule_gate_service.try_resolve(message, context={})
        tool_name = rule.get("tool_name") if rule else None
        self._expect(case, "tool", tool_name)
        if case.get("expect_recall_category") is not None:
            recall_plan = agent_memory_recall_policy_service.build_plan(message, {})
            self._expect_value(case, "recall_category", recall_plan.category)
        if case.get("expect_tool_value") is not None:
            self._expect_value(case, "tool_value", (rule or {}).get("tool_args", {}).get("value"))

        intent = self._intent_from_case(rule, case)
        tool_result = self._tool_result_from_case(case)
        response = self._response_from_case(case, tool_result)
        candidates = agent_memory_extraction_service.extract_candidates(
            db=db,
            student_id=self.student_id,
            course_id=self.course_id,
            user_message=message,
            intent_result=intent,
            tool_result=tool_result,
            response=response,
            context={},
        )

        name_candidate = self._find_candidate(candidates, "profile", "name")
        expected_name = case.get("expect_name_value")
        actual_name = None
        if name_candidate and isinstance(name_candidate.memory_value_json, dict):
            actual_name = name_candidate.memory_value_json.get("name")
        self._expect_value(case, "name_value", actual_name)
        if case.get("expect_utterance_type") is not None and name_candidate:
            self._expect_value(case, "utterance_type", name_candidate.utterance_type)

        expected_topic = case.get("expect_topic")
        if expected_topic is not None:
            topic_candidate = self._find_candidate(candidates, "episodic", case.get("expect_memory_key"))
            actual_topic = None
            if topic_candidate and isinstance(topic_candidate.memory_value_json, dict):
                actual_topic = topic_candidate.memory_value_json.get("topic")
            self._expect_value(case, "topic", actual_topic)
        self._expect_memory_candidate(case, candidates)

        result = agent_memory_extraction_service.extract_and_persist(
            db=db,
            student_id=self.student_id,
            course_id=self.course_id,
            user_message=message,
            intent_result=intent,
            tool_result=tool_result,
            response=response,
            context={},
        )
        db.commit()

        if case.get("expect_written_count") is not None:
            self._expect_value(case, "written_count", result.get("written_count"))

        expected_policy_action = case.get("expect_policy_action")
        if expected_policy_action is not None:
            actual_action = None
            for decision in result.get("policy_decisions") or []:
                if decision.get("reason") != "memory_recall_question_is_read_only":
                    actual_action = decision.get("action")
                    break
            self._expect_value(case, "policy_action", actual_action)

        if case.get("expect_written_value") is not None:
            memory = agent_long_term_memory_service.find_active_memory_by_key(
                db=db,
                student_id=self.student_id,
                course_id=None,
                memory_type="profile",
                memory_key="name",
            )
            value = None
            if memory and isinstance(memory.memory_value_json, dict):
                value = memory.memory_value_json.get("name")
            self._expect_value(case, "written_value", value)
        self._expect_written_memory(db, case)

    def _intent_from_case(self, rule: dict | None, case: dict) -> IntentRouterResult:
        if rule:
            return IntentRouterResult.from_rule(rule)
        return IntentRouterResult(
            is_learning_related=True,
            domain="learning",
            intent="qa_answer",
            confidence=0.9,
            refers_to_previous_message=False,
            topic=case.get("intent_topic"),
            knowledge_point_ids=[],
            need_clarification=False,
            tool_name=case.get("intent_tool") or "qa_answer",
            tool_args={},
            answer_strategy="normal",
            reason="[memory_regression] synthetic intent",
        )

    def _tool_result_from_case(self, case: dict) -> dict:
        return case.get("tool_result") or {
            "type": "answer",
            "text": "测试回答",
            "related_knowledge_point_ids": [],
        }

    def _response_from_case(self, case: dict, tool_result: dict) -> dict:
        return case.get("response") or {
            "text": tool_result.get("text") or "测试回答",
            "related_knowledge_point_ids": tool_result.get("related_knowledge_point_ids") or [],
        }

    @staticmethod
    def _find_candidate(candidates, memory_type: str, memory_key: str | None):
        for candidate in candidates:
            if candidate.memory_type == memory_type and (memory_key is None or candidate.memory_key == memory_key):
                return candidate
        return None

    def _expect_memory_candidate(self, case: dict, candidates) -> None:
        expected = case.get("expect_memory")
        if not expected:
            return
        candidate = self._find_candidate(candidates, expected["memory_type"], expected.get("memory_key"))
        if not candidate:
            self.failures.append(
                MemoryRegressionFailure(
                    case_id=case["id"],
                    detail=f"memory candidate: expected {expected['memory_type']}/{expected.get('memory_key')}, got None",
                )
            )
            return
        self._expect_memory_like(case, "memory_candidate", candidate, expected)

    def _expect_written_memory(self, db, case: dict) -> None:
        expected = case.get("expect_written_memory")
        if not expected:
            return
        course_id = self.course_id if expected.get("course_scope", "course") == "course" else None
        memory = agent_long_term_memory_service.find_active_memory_by_key(
            db=db,
            student_id=self.student_id,
            course_id=course_id,
            memory_type=expected["memory_type"],
            memory_key=expected["memory_key"],
        )
        if not memory:
            self.failures.append(
                MemoryRegressionFailure(
                    case_id=case["id"],
                    detail=f"written memory: expected {expected['memory_type']}/{expected['memory_key']}, got None",
                )
            )
            return
        self._expect_memory_like(case, "written_memory", memory, expected)

    def _expect_memory_like(self, case: dict, label: str, memory, expected: dict) -> None:
        expected_scope = expected.get("course_scope")
        if expected_scope is not None:
            actual_scope = self._memory_scope(memory)
            if actual_scope != expected_scope:
                self.failures.append(
                    MemoryRegressionFailure(
                        case_id=case["id"],
                        detail=f"{label}.course_scope: expected {expected_scope!r}, got {actual_scope!r}",
                    )
                )

        if "value" in expected:
            value = getattr(memory, "memory_value_json", None)
            missing = self._missing_subset(value, expected["value"])
            if missing:
                self.failures.append(
                    MemoryRegressionFailure(
                        case_id=case["id"],
                        detail=f"{label}.value: missing {missing!r} in {value!r}",
                    )
                )

    def _memory_scope(self, memory) -> str:
        if hasattr(memory, "course_scope"):
            return getattr(memory, "course_scope")
        return "global" if getattr(memory, "course_id", None) is None else "course"

    def _missing_subset(self, actual, expected):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                return expected
            missing = {}
            for key, expected_value in expected.items():
                if key not in actual:
                    missing[key] = expected_value
                    continue
                child_missing = self._missing_subset(actual.get(key), expected_value)
                if child_missing not in (None, {}, []):
                    missing[key] = child_missing
            return missing
        if isinstance(expected, list):
            if not isinstance(actual, list):
                return expected
            return [item for item in expected if item not in actual]
        return None if actual == expected else expected

    def _expect(self, case: dict, key: str, actual) -> None:
        expected = case.get(f"expect_{key}")
        if expected != actual:
            self.failures.append(
                MemoryRegressionFailure(
                    case_id=case["id"],
                    detail=f"{key}: expected {expected!r}, got {actual!r}",
                )
            )

    def _expect_value(self, case: dict, key: str, actual) -> None:
        expected_key = f"expect_{key}"
        if expected_key not in case:
            return
        expected = case.get(expected_key)
        if expected != actual:
            self.failures.append(
                MemoryRegressionFailure(
                    case_id=case["id"],
                    detail=f"{key}: expected {expected!r}, got {actual!r}",
                )
            )

    def _cleanup(self, db) -> None:
        db.query(AgentMemoryEvent).filter(AgentMemoryEvent.student_id == self.student_id).delete(synchronize_session=False)
        db.query(AgentMemory).filter(AgentMemory.student_id == self.student_id).delete(synchronize_session=False)


if __name__ == "__main__":
    raise SystemExit(MemoryRegressionRunner().run())
