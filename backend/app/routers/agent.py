from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationResponse,
    AgentMessageResponse,
)
from app.security import get_current_user
from app.services.agent_conversation_service import agent_conversation_service
from app.services.course_permission_service import course_permission_service


router = APIRouter()


@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(
    req: AgentChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        # 校验课程访问权限（文档 Section 12.1 / 19.6）
        course_permission_service.require_view_course(db, current_user, req.course_id)

        # 配置开关：enable_llm_intent_router（文档 Section 21 Step 8）
        if settings.enable_llm_intent_router:
            from app.services.agent_orchestrator_service import agent_orchestrator_service

            return agent_orchestrator_service.chat(
                db=db,
                student_id=current_user.id,
                course_id=req.course_id,
                message=req.message,
                conversation_id=req.conversation_id,
                include_debug=(settings.app_env == "dev"),
            )
        else:
            from app.services.agent_router_service import agent_router_service

            return agent_router_service.chat(
                db=db,
                student_id=current_user.id,
                course_id=req.course_id,
                message=req.message,
                conversation_id=req.conversation_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/conversations/recent", response_model=AgentConversationResponse)
def get_recent_conversation(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    course_permission_service.require_view_course(db, current_user, course_id)
    conversation = agent_conversation_service.get_recent_conversation(
        db=db,
        student_id=current_user.id,
        course_id=course_id,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="暂无最近会话")
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[AgentMessageResponse])
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        conversation = agent_conversation_service.get_conversation_by_id(
            db=db,
            student_id=current_user.id,
            conversation_id=conversation_id,
        )
        # 校验课程访问权限（文档 Section 19.6）
        course_permission_service.require_view_course(db, current_user, conversation.course_id)
        messages = agent_conversation_service.get_recent_messages(
            db=db,
            conversation_id=conversation.id,
            limit=100,
        )
        return messages
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
