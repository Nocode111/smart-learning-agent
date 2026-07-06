"""Smoke test for Graphiti integration in disabled/unavailable mode.

This verifies that the optional Graphiti layer does not break the Agent when
Neo4j/FalkorDB or graphiti-core is not available.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_graphiti_memory_service import agent_graphiti_memory_service


async def main() -> int:
    status = agent_graphiti_memory_service.status()
    result = await agent_graphiti_memory_service.search(
        student_id=987650003,
        course_id=1,
        query="缓存命中",
    )
    assert result["available"] is False
    assert result["facts"] == []
    assert result["context_text"] == ""
    print("graphiti disabled smoke: passed")
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
