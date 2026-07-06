"""HTTP adapter for the independent Graphiti memory service.

The main backend intentionally does not import graphiti-core. Graphiti runs in
its own service so its pydantic and graph database dependencies stay isolated.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AgentGraphitiMemoryService:
    def __init__(self):
        self._last_error: str | None = None
        self._last_available: bool = False

    def is_enabled(self) -> bool:
        return bool(settings.enable_agent_graphiti)

    def status(self) -> dict[str, Any]:
        missing = []
        if not settings.graphiti_service_url:
            missing.append("GRAPHITI_SERVICE_URL")
        return {
            "enabled": self.is_enabled(),
            "configured": not missing,
            "missing": missing,
            "service_url": settings.graphiti_service_url,
            "available": self._last_available,
            "init_error": self._last_error,
        }

    async def ensure_ready(self) -> bool:
        if not self.is_enabled():
            self._last_available = False
            return False
        if not settings.graphiti_service_url:
            self._last_available = False
            self._last_error = "missing_config:GRAPHITI_SERVICE_URL"
            return False

        try:
            data = await self._request("GET", "/health")
            configured = bool(data.get("configured"))
            self._last_available = bool(data.get("available"))
            self._last_error = data.get("init_error")
            if not configured and not self._last_error:
                self._last_error = f"graphiti_service_missing:{','.join(data.get('missing') or [])}"
            return configured
        except Exception as exc:
            self._last_available = False
            self._last_error = str(exc)
            logger.warning("Graphiti service health check failed: %s", exc)
            return False

    async def close(self) -> None:
        return None

    async def search(self, student_id: int, course_id: int | None, query: str, limit: int | None = None) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {
                "enabled": self.is_enabled(),
                "available": False,
                "facts": [],
                "context_text": "",
                "error": self._last_error,
            }

        payload = {
            "student_id": student_id,
            "course_id": course_id,
            "query": query,
            "limit": limit or settings.graphiti_search_limit,
        }
        try:
            data = await self._request("POST", "/search", payload)
            self._last_available = bool(data.get("available"))
            return {
                "enabled": bool(data.get("enabled", True)),
                "available": bool(data.get("available")),
                "group_ids": data.get("group_ids") or [],
                "facts": data.get("facts") or [],
                "context_text": data.get("context_text") or "",
                "error": data.get("error"),
            }
        except Exception as exc:
            self._last_available = False
            self._last_error = str(exc)
            logger.warning("Graphiti service search failed: %s", exc)
            return {"enabled": True, "available": False, "error": str(exc), "facts": [], "context_text": ""}

    def search_sync(self, student_id: int, course_id: int | None, query: str, limit: int | None = None) -> dict[str, Any]:
        return self._run_async_safely(
            self.search(student_id=student_id, course_id=course_id, query=query, limit=limit)
        ) or {"enabled": self.is_enabled(), "available": False, "facts": [], "context_text": ""}

    async def add_memory_episode(
        self,
        student_id: int,
        course_id: int | None,
        memory,
        reference_time: datetime | None = None,
    ) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {"enabled": self.is_enabled(), "written": False, "reason": self._last_error or "graphiti_disabled"}

        payload = self._to_jsonable(
            {
                "student_id": student_id,
                "course_id": course_id,
                "memory_id": getattr(memory, "id", None),
                "memory_type": getattr(memory, "memory_type", None),
                "memory_key": getattr(memory, "memory_key", None),
                "memory_text": getattr(memory, "memory_text", None),
                "memory_value_json": getattr(memory, "memory_value_json", None),
                "confidence": getattr(memory, "confidence", None),
                "importance": getattr(memory, "importance", None),
                "reference_time": reference_time,
            }
        )
        try:
            data = await self._request("POST", "/episodes/memory", payload)
            self._last_available = bool(data.get("written"))
            return data
        except Exception as exc:
            self._last_available = False
            self._last_error = str(exc)
            logger.warning("Graphiti service memory write failed: %s", exc)
            return {"enabled": True, "written": False, "error": str(exc)}

    def add_memory_episode_sync(
        self,
        student_id: int,
        course_id: int | None,
        memory,
        reference_time: datetime | None = None,
    ) -> dict[str, Any]:
        return self._run_async_safely(
            self.add_memory_episode(
                student_id=student_id,
                course_id=course_id,
                memory=memory,
                reference_time=reference_time,
            )
        ) or {"enabled": self.is_enabled(), "written": False, "reason": "running_event_loop"}

    async def add_learning_event_episode(
        self,
        student_id: int,
        course_id: int | None,
        event_name: str,
        payload: dict[str, Any],
        reference_time: datetime | None = None,
    ) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {"enabled": self.is_enabled(), "written": False, "reason": self._last_error or "graphiti_disabled"}

        request_payload = self._to_jsonable(
            {
                "student_id": student_id,
                "course_id": course_id,
                "event_name": event_name,
                "payload": payload or {},
                "reference_time": reference_time,
            }
        )
        try:
            data = await self._request("POST", "/episodes/learning-event", request_payload)
            self._last_available = bool(data.get("written"))
            return data
        except Exception as exc:
            self._last_available = False
            self._last_error = str(exc)
            logger.warning("Graphiti service learning event write failed: %s", exc)
            return {"enabled": True, "written": False, "error": str(exc)}

    async def add_episode(
        self,
        student_id: int,
        course_id: int | None,
        name: str,
        payload: dict[str, Any],
        source_description: str,
        reference_time: datetime | None = None,
    ) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {"enabled": self.is_enabled(), "written": False, "reason": self._last_error or "graphiti_disabled"}

        request_payload = self._to_jsonable(
            {
                "student_id": student_id,
                "course_id": course_id,
                "name": name,
                "payload": payload or {},
                "source_description": source_description,
                "reference_time": reference_time,
            }
        )
        try:
            data = await self._request("POST", "/episodes", request_payload)
            self._last_available = bool(data.get("written"))
            return data
        except Exception as exc:
            self._last_available = False
            self._last_error = str(exc)
            logger.warning("Graphiti service episode write failed: %s", exc)
            return {"enabled": True, "written": False, "error": str(exc)}

    @staticmethod
    def format_context_text(facts: list[dict[str, Any]]) -> str:
        if not facts:
            return ""
        lines = ["【图谱记忆关系】"]
        for item in facts[: settings.graphiti_search_limit]:
            fact = item.get("fact") or item.get("name") or ""
            if fact:
                lines.append(f"- {fact}")
        return "\n".join(lines)

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        base_url = settings.graphiti_service_url.rstrip("/")
        url = f"{base_url}{path}"
        timeout = httpx.Timeout(settings.graphiti_http_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(url)
            else:
                response = await client.post(url, json=payload or {})
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _run_async_safely(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        coro.close()
        logger.warning("Current event loop is running; skipped synchronous Graphiti service call")
        return None

    @classmethod
    def _to_jsonable(cls, value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): cls._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._to_jsonable(item) for item in value]
        return value


agent_graphiti_memory_service = AgentGraphitiMemoryService()
