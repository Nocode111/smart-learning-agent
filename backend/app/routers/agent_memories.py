"""
Agent 长期记忆管理 API。

第三阶段：提供自建 memory tables 的基础管理能力。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.agent_memory import (
    AgentMemoryContextResponse,
    AgentMemoryCreateRequest,
    AgentMemoryEventResponse,
    AgentMemoryFeedbackRequest,
    AgentMemoryListResponse,
    AgentMemoryResponse,
    AgentMemorySummaryCreateRequest,
    AgentMemorySummaryResponse,
    AgentMemoryUpdateRequest,
)
from app.security import get_current_user
from app.services.agent_long_term_memory_service import agent_long_term_memory_service
from app.services.course_permission_service import course_permission_service

router = APIRouter()


def _check_course_if_needed(db: Session, current_user: User, course_id: int | None) -> None:
    if course_id is not None:
        course_permission_service.require_view_course(db, current_user, course_id)


@router.get("", response_model=AgentMemoryListResponse)
def list_memories(
    course_id: int | None = Query(None, alias="courseId"),
    memory_type: str | None = Query(None, alias="memoryType"),
    status: str = Query("active"),
    q: str | None = Query(None),
    include_global: bool = Query(True, alias="includeGlobal"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_course_if_needed(db, current_user, course_id)
    items = agent_long_term_memory_service.list_memories(
        db=db,
        student_id=current_user.id,
        course_id=course_id,
        memory_type=memory_type,
        status=status,
        q=q,
        include_global=include_global,
        limit=limit,
    )
    return AgentMemoryListResponse(items=[AgentMemoryResponse.model_validate(item) for item in items])


@router.post("", response_model=AgentMemoryResponse)
def create_memory(
    req: AgentMemoryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_course_if_needed(db, current_user, req.course_id)
    try:
        memory = agent_long_term_memory_service.create_memory(
            db=db,
            student_id=current_user.id,
            course_id=req.course_id,
            memory_type=req.memory_type,
            memory_key=req.memory_key,
            memory_text=req.memory_text,
            memory_value_json=req.memory_value_json,
            confidence=req.confidence,
            importance=req.importance,
            source_type=req.source_type or "manual",
            source_id=req.source_id,
            expires_at=req.expires_at,
        )
        db.commit()
        db.refresh(memory)
        return AgentMemoryResponse.model_validate(memory)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/context", response_model=AgentMemoryContextResponse)
def get_memory_context(
    course_id: int | None = Query(None, alias="courseId"),
    message: str | None = Query(None),
    per_type_limit: int = Query(5, alias="perTypeLimit", ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_course_if_needed(db, current_user, course_id)
    context = agent_long_term_memory_service.build_memory_context(
        db=db,
        student_id=current_user.id,
        course_id=course_id,
        message=message,
        per_type_limit=per_type_limit,
    )
    db.commit()
    return AgentMemoryContextResponse(
        profile_memories=[AgentMemoryResponse.model_validate(item) for item in context["profile_memories"]],
        preference_memories=[AgentMemoryResponse.model_validate(item) for item in context["preference_memories"]],
        learning_state_memories=[AgentMemoryResponse.model_validate(item) for item in context["learning_state_memories"]],
        episodic_memories=[AgentMemoryResponse.model_validate(item) for item in context["episodic_memories"]],
        semantic_memories=[AgentMemoryResponse.model_validate(item) for item in context["semantic_memories"]],
        procedural_memories=[AgentMemoryResponse.model_validate(item) for item in context["procedural_memories"]],
        memory_context_text=context["memory_context_text"],
    )


@router.get("/events", response_model=list[AgentMemoryEventResponse])
def list_memory_events(
    memory_id: int | None = Query(None, alias="memoryId"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if memory_id:
        agent_long_term_memory_service.get_memory(db, memory_id, current_user.id)
    events = agent_long_term_memory_service.list_events(
        db=db,
        student_id=current_user.id,
        memory_id=memory_id,
        limit=limit,
    )
    return [AgentMemoryEventResponse.model_validate(item) for item in events]


@router.post("/summaries", response_model=AgentMemorySummaryResponse)
def create_memory_summary(
    req: AgentMemorySummaryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_course_if_needed(db, current_user, req.course_id)
    summary = agent_long_term_memory_service.create_summary(
        db=db,
        student_id=current_user.id,
        course_id=req.course_id,
        conversation_id=req.conversation_id,
        summary_type=req.summary_type,
        summary_text=req.summary_text,
        covered_message_ids_json=req.covered_message_ids_json,
        related_knowledge_point_ids_json=req.related_knowledge_point_ids_json,
    )
    db.commit()
    db.refresh(summary)
    return AgentMemorySummaryResponse.model_validate(summary)


@router.get("/{memory_id}", response_model=AgentMemoryResponse)
def get_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        memory = agent_long_term_memory_service.get_memory(db, memory_id, current_user.id)
        _check_course_if_needed(db, current_user, memory.course_id)
        return AgentMemoryResponse.model_validate(memory)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{memory_id}", response_model=AgentMemoryResponse)
def update_memory(
    memory_id: int,
    req: AgentMemoryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_course_if_needed(db, current_user, req.course_id)
    try:
        updates = req.model_dump(exclude_unset=True)
        memory = agent_long_term_memory_service.update_memory(
            db=db,
            memory_id=memory_id,
            student_id=current_user.id,
            **updates,
        )
        db.commit()
        db.refresh(memory)
        return AgentMemoryResponse.model_validate(memory)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{memory_id}/disable", response_model=AgentMemoryResponse)
def disable_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        memory = agent_long_term_memory_service.disable_memory(
            db=db,
            memory_id=memory_id,
            student_id=current_user.id,
        )
        db.commit()
        db.refresh(memory)
        return AgentMemoryResponse.model_validate(memory)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{memory_id}", response_model=AgentMemoryResponse)
def delete_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        memory = agent_long_term_memory_service.delete_memory(
            db=db,
            memory_id=memory_id,
            student_id=current_user.id,
        )
        db.commit()
        db.refresh(memory)
        return AgentMemoryResponse.model_validate(memory)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{memory_id}/feedback")
def add_memory_feedback(
    memory_id: int,
    req: AgentMemoryFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        feedback = agent_long_term_memory_service.add_feedback(
            db=db,
            memory_id=memory_id,
            student_id=current_user.id,
            action=req.action,
            feedback_text=req.feedback_text,
        )
        db.commit()
        return {
            "id": feedback.id,
            "memory_id": feedback.memory_id,
            "action": feedback.action,
            "message": "记忆反馈已记录",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))

