"""Smoke test for memory recall policy and answer composition.

Usage:
    python scripts/run_memory_recall_policy_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_tool_executor_service import agent_tool_executor_service


def make_context() -> dict:
    return {
        "long_term_memory": {
            "profile_memories": [
                SimpleNamespace(
                    memory_key="name",
                    memory_text="用户的名字是懒洋洋。",
                    memory_value_json={"name": "懒洋洋"},
                    importance=1.0,
                    confidence=1.0,
                )
            ],
            "preference_memories": [],
            "learning_state_memories": [],
            "episodic_memories": [
                SimpleNamespace(
                    memory_key="recent_learning_topic_1",
                    memory_text="用户最近说缓存命中这个知识点掌握得不好。",
                    memory_value_json={"topic": "缓存命中"},
                    importance=0.9,
                    confidence=0.9,
                )
            ],
            "semantic_memories": [],
            "procedural_memories": [],
        },
        "memory_context_text": (
            "【用户画像记忆】\n"
            "- 用户的名字是懒洋洋。\n\n"
            "【历史事件记忆】\n"
            "- 用户最近说缓存命中这个知识点掌握得不好。"
        ),
    }


def main() -> int:
    context = make_context()

    learning = agent_tool_executor_service._memory_recall(
        context,
        "我刚刚说我哪个知识点掌握得不好？",
    )
    assert "缓存命中" in learning["text"]
    assert "懒洋洋" not in learning["text"]
    assert learning["memory_recall"]["category"] == "learning_weakness"

    name = agent_tool_executor_service._memory_recall(
        context,
        "你还记得我叫什么名字吗？",
    )
    assert "懒洋洋" in name["text"]
    assert "缓存命中" not in name["text"]
    assert name["memory_recall"]["category"] == "identity_name"

    print("memory recall policy smoke: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
