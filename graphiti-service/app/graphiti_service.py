from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class GraphitiMemoryService:
    def __init__(self):
        self._client = None
        self._init_error: str | None = None

    def status(self) -> dict[str, Any]:
        missing = []
        if not settings.dashscope_api_key:
            missing.append("DASHSCOPE_API_KEY")
        if not settings.graphiti_uri:
            missing.append("GRAPHITI_URI")
        if not settings.graphiti_user:
            missing.append("GRAPHITI_USER")
        if not settings.graphiti_password:
            missing.append("GRAPHITI_PASSWORD")
        return {
            "status": "ok",
            "configured": not missing,
            "missing": missing,
            "available": self._client is not None,
            "init_error": self._init_error,
        }

    async def ensure_ready(self) -> bool:
        status = self.status()
        if not status["configured"]:
            self._init_error = f"missing_config:{','.join(status['missing'])}"
            return False
        if self._client is not None:
            return True

        try:
            self._ensure_openai_compatible_env()

            from graphiti_core import Graphiti
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

            llm_config = LLMConfig(
                api_key=settings.dashscope_api_key,
                model=settings.qwen_chat_model,
                small_model=settings.qwen_chat_model,
                base_url=settings.dashscope_base_url,
                temperature=0,
            )
            llm_client = OpenAIGenericClient(config=llm_config, structured_output_mode="json_object")
            embedder = OpenAIEmbedder(
                config=OpenAIEmbedderConfig(
                    api_key=settings.dashscope_api_key,
                    base_url=settings.dashscope_base_url,
                    embedding_model=settings.qwen_embedding_model,
                )
            )
            self._client = Graphiti(
                uri=settings.graphiti_uri,
                user=settings.graphiti_user,
                password=settings.graphiti_password,
                llm_client=llm_client,
                embedder=embedder,
            )
            if settings.graphiti_build_indices_on_start:
                await self._client.build_indices_and_constraints()
            self._init_error = None
            return True
        except Exception as exc:
            self._client = None
            self._init_error = str(exc)
            logger.exception("Graphiti initialization failed")
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def build_indices(self) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {"ok": False, "error": self._init_error or "graphiti_unavailable"}
        try:
            await self._client.build_indices_and_constraints()
            return {"ok": True}
        except Exception as exc:
            logger.exception("Graphiti index initialization failed")
            return {"ok": False, "error": str(exc)}

    async def search(self, student_id: int, course_id: int | None, query: str, limit: int | None = None) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {
                "enabled": True,
                "available": False,
                "group_ids": [],
                "facts": [],
                "context_text": "",
                "error": self._init_error,
            }

        group_ids = self._group_ids(student_id=student_id, course_id=course_id)
        try:
            results = await self._client.search(
                query=query,
                group_ids=group_ids,
                num_results=limit or settings.graphiti_search_limit,
            )
            facts = [self._edge_to_fact(item) for item in results]
            facts = [item for item in facts if item]
            if not facts:
                facts = await self._retrieve_episode_facts(group_ids=group_ids, limit=limit or settings.graphiti_search_limit)
            return {
                "enabled": True,
                "available": True,
                "group_ids": group_ids,
                "facts": facts,
                "context_text": self.format_context_text(facts),
            }
        except Exception as exc:
            logger.exception("Graphiti search failed")
            return {
                "enabled": True,
                "available": False,
                "group_ids": group_ids,
                "facts": [],
                "context_text": "",
                "error": str(exc),
            }

    async def add_memory_episode(
        self,
        student_id: int,
        course_id: int | None,
        memory_id: int | None,
        memory_type: str | None,
        memory_key: str | None,
        memory_text: str | None,
        memory_value_json: Any | None,
        confidence: float | None,
        importance: float | None,
        reference_time: datetime | None = None,
    ) -> dict[str, Any]:
        payload = {
            "event_type": "long_term_memory",
            "student_id": student_id,
            "course_id": course_id,
            "memory_id": memory_id,
            "memory_type": memory_type,
            "memory_key": memory_key,
            "memory_text": memory_text,
            "memory_value_json": memory_value_json,
            "confidence": confidence,
            "importance": importance,
        }
        name = f"memory:{memory_type or 'unknown'}:{memory_key or 'unknown'}"
        return await self.add_episode(
            student_id=student_id,
            course_id=course_id,
            name=name,
            payload=payload,
            source_description="smart-learning-agent long-term memory",
            reference_time=reference_time,
            source_type="text",
            episode_body=self._format_memory_episode_text(payload),
        )

    async def add_learning_event_episode(
        self,
        student_id: int,
        course_id: int | None,
        event_name: str,
        payload: dict[str, Any],
        reference_time: datetime | None = None,
    ) -> dict[str, Any]:
        episode_payload = {
            "event_type": "learning_event",
            "student_id": student_id,
            "course_id": course_id,
            **(payload or {}),
        }
        return await self.add_episode(
            student_id=student_id,
            course_id=course_id,
            name=event_name,
            payload=episode_payload,
            source_description="smart-learning-agent learning event",
            reference_time=reference_time,
        )

    async def add_episode(
        self,
        student_id: int,
        course_id: int | None,
        name: str,
        payload: dict[str, Any],
        source_description: str,
        reference_time: datetime | None = None,
        source_type: str = "json",
        episode_body: str | None = None,
    ) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {
                "enabled": True,
                "written": False,
                "reason": self._init_error or "graphiti_unavailable",
            }

        try:
            from graphiti_core.nodes import EpisodeType

            episode_type = getattr(EpisodeType, source_type, EpisodeType.json)
            group_id = self._group_id(student_id=student_id, course_id=course_id)
            result = await self._client.add_episode(
                name=name,
                episode_body=episode_body or json.dumps(payload, ensure_ascii=False, default=str),
                source_description=source_description,
                reference_time=reference_time or datetime.now(timezone.utc),
                source=episode_type,
                group_id=group_id,
            )
            return {
                "enabled": True,
                "written": True,
                "group_id": group_id,
                "episode_uuid": getattr(getattr(result, "episode", None), "uuid", None),
            }
        except Exception as exc:
            logger.exception("Graphiti episode write failed")
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

    @staticmethod
    def _edge_to_fact(edge: Any) -> dict[str, Any]:
        fact = getattr(edge, "fact", None) or getattr(edge, "name", None) or str(edge)
        return {
            "uuid": getattr(edge, "uuid", None),
            "name": getattr(edge, "name", None),
            "fact": fact,
            "valid_at": getattr(edge, "valid_at", None),
            "invalid_at": getattr(edge, "invalid_at", None),
            "source_node_uuid": getattr(edge, "source_node_uuid", None),
            "target_node_uuid": getattr(edge, "target_node_uuid", None),
        }

    def _group_ids(self, student_id: int, course_id: int | None) -> list[str]:
        group_ids = [self._group_id(student_id=student_id, course_id=None)]
        if course_id is not None:
            group_ids.append(self._group_id(student_id=student_id, course_id=course_id))
        return group_ids

    async def _retrieve_episode_facts(self, group_ids: list[str], limit: int) -> list[dict[str, Any]]:
        try:
            episodes = await self._client.retrieve_episodes(
                reference_time=datetime.now(timezone.utc),
                last_n=limit,
                group_ids=group_ids,
            )
        except Exception as exc:
            logger.warning("Graphiti episode fallback search failed: %s", exc)
            return []

        facts = []
        for episode in episodes or []:
            content = getattr(episode, "content", None) or getattr(episode, "episode_body", None) or ""
            name = getattr(episode, "name", None) or ""
            fact = content or name
            if not fact:
                continue
            facts.append(
                {
                    "uuid": getattr(episode, "uuid", None),
                    "name": name,
                    "fact": fact,
                    "source": "episode",
                    "valid_at": getattr(episode, "valid_at", None),
                    "group_id": getattr(episode, "group_id", None),
                }
            )
        return facts

    @staticmethod
    def _group_id(student_id: int, course_id: int | None) -> str:
        if course_id is None:
            return f"{settings.graphiti_group_prefix}_student_{student_id}_global"
        return f"{settings.graphiti_group_prefix}_student_{student_id}_course_{course_id}"

    @staticmethod
    def _format_memory_episode_text(payload: dict[str, Any]) -> str:
        student_id = payload.get("student_id")
        course_id = payload.get("course_id")
        memory_type = payload.get("memory_type") or "unknown"
        memory_key = payload.get("memory_key") or "unknown"
        memory_text = payload.get("memory_text") or ""
        value = payload.get("memory_value_json")
        lines = [
            f"学生 {student_id} 的长期记忆：{memory_text}",
            f"记忆类型：{memory_type}",
            f"记忆键：{memory_key}",
        ]
        if course_id is not None:
            lines.append(f"课程ID：{course_id}")
        if value is not None:
            lines.append(f"结构化值：{json.dumps(value, ensure_ascii=False, default=str)}")
        return "\n".join(lines)

    @staticmethod
    def _ensure_openai_compatible_env() -> None:
        if settings.dashscope_api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = settings.dashscope_api_key
        if settings.dashscope_base_url and not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = settings.dashscope_base_url


graphiti_memory_service = GraphitiMemoryService()
