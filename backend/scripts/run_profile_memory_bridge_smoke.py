"""Smoke test for profile-memory bridge.

Usage:
    python scripts/run_profile_memory_bridge_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models.agent_memory import AgentMemory, AgentMemoryEvent
from app.models.profile import StudentKnowledgeMastery, StudentProfile
from app.services.agent_long_term_memory_service import agent_long_term_memory_service
from app.services.agent_profile_memory_bridge_service import agent_profile_memory_bridge_service
from app.services.profile_service import profile_service


STUDENT_ID = 987650002
COURSE_ID = 1
KNOWLEDGE_POINT_ID = 1


def cleanup(db) -> None:
    db.query(AgentMemoryEvent).filter(AgentMemoryEvent.student_id == STUDENT_ID).delete(synchronize_session=False)
    db.query(AgentMemory).filter(AgentMemory.student_id == STUDENT_ID).delete(synchronize_session=False)
    db.query(StudentKnowledgeMastery).filter(StudentKnowledgeMastery.student_id == STUDENT_ID).delete(synchronize_session=False)
    db.query(StudentProfile).filter(StudentProfile.student_id == STUDENT_ID).delete(synchronize_session=False)


def main() -> int:
    db = SessionLocal()
    try:
        cleanup(db)
        db.commit()

        profile = profile_service.get_or_create_profile(db, STUDENT_ID, COURSE_ID)
        profile.overall_level = "基础薄弱"
        mastery = profile_service.get_or_create_mastery(db, STUDENT_ID, COURSE_ID, KNOWLEDGE_POINT_ID)
        mastery.mastery_score = 35
        mastery.ask_count = 2
        mastery.unresolved_count = 1

        agent_long_term_memory_service.create_memory(
            db=db,
            student_id=STUDENT_ID,
            course_id=None,
            memory_type="preference",
            memory_key="explain_with_examples",
            memory_text="用户偏好用简单例子解释知识点。",
            memory_value_json={"style": "examples"},
            confidence=0.9,
            importance=0.8,
            source_type="profile_memory_bridge_smoke",
        )
        agent_long_term_memory_service.create_memory(
            db=db,
            student_id=STUDENT_ID,
            course_id=COURSE_ID,
            memory_type="episodic",
            memory_key="last_asked_topic",
            memory_text="用户最近问过的知识点是“缓存命中”。",
            memory_value_json={"topic": "缓存命中"},
            confidence=0.9,
            importance=0.75,
            source_type="profile_memory_bridge_smoke",
        )
        db.commit()

        memory_context = agent_long_term_memory_service.build_memory_context(
            db=db,
            student_id=STUDENT_ID,
            course_id=COURSE_ID,
            message="你根据我的情况讲一下缓存命中",
        )
        bridged = agent_profile_memory_bridge_service.build_context(
            db=db,
            student_id=STUDENT_ID,
            course_id=COURSE_ID,
            memory_context=memory_context,
        )

        merged = bridged["learning_profile_with_memory"]
        text = bridged["learning_profile_memory_context_text"]
        assert merged["overall_level"] == "基础薄弱"
        assert merged["memory_supplements"]["preferences"]
        assert merged["memory_supplements"]["recent_learning_events"]
        assert "学习画像权威数据" in text
        assert "长期记忆补充：学习偏好" in text
        assert "掌握度、薄弱点、整体水平以学习画像表为准" in text
        print("profile-memory bridge smoke: passed")
        return 0
    finally:
        cleanup(db)
        db.commit()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
