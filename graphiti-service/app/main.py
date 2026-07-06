from __future__ import annotations

import logging

from fastapi import FastAPI

from app.graphiti_service import graphiti_memory_service
from app.schemas import (
    BuildIndicesResponse,
    EpisodeRequest,
    EpisodeWriteResponse,
    HealthResponse,
    LearningEventEpisodeRequest,
    MemoryEpisodeRequest,
    SearchRequest,
    SearchResponse,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smart Learning Graphiti Service")


@app.get("/health", response_model=HealthResponse)
async def health() -> dict:
    return graphiti_memory_service.status()


@app.post("/admin/build-indices", response_model=BuildIndicesResponse)
async def build_indices() -> dict:
    return await graphiti_memory_service.build_indices()


@app.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest) -> dict:
    return await graphiti_memory_service.search(
        student_id=payload.student_id,
        course_id=payload.course_id,
        query=payload.query,
        limit=payload.limit,
    )


@app.post("/episodes/memory", response_model=EpisodeWriteResponse)
async def add_memory_episode(payload: MemoryEpisodeRequest) -> dict:
    return await graphiti_memory_service.add_memory_episode(
        student_id=payload.student_id,
        course_id=payload.course_id,
        memory_id=payload.memory_id,
        memory_type=payload.memory_type,
        memory_key=payload.memory_key,
        memory_text=payload.memory_text,
        memory_value_json=payload.memory_value_json,
        confidence=payload.confidence,
        importance=payload.importance,
        reference_time=payload.reference_time,
    )


@app.post("/episodes/learning-event", response_model=EpisodeWriteResponse)
async def add_learning_event_episode(payload: LearningEventEpisodeRequest) -> dict:
    return await graphiti_memory_service.add_learning_event_episode(
        student_id=payload.student_id,
        course_id=payload.course_id,
        event_name=payload.event_name,
        payload=payload.payload,
        reference_time=payload.reference_time,
    )


@app.post("/episodes", response_model=EpisodeWriteResponse)
async def add_episode(payload: EpisodeRequest) -> dict:
    return await graphiti_memory_service.add_episode(
        student_id=payload.student_id,
        course_id=payload.course_id,
        name=payload.name,
        payload=payload.payload,
        source_description=payload.source_description,
        source_type=payload.source_type,
        reference_time=payload.reference_time,
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    await graphiti_memory_service.close()
