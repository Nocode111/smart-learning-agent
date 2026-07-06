from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.behavior_service import behavior_service
from app.services.profile_service import profile_service
from app.services.course_permission_service import course_permission_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


class BehaviorCreate(BaseModel):
    course_id: int | None = None
    knowledge_point_id: int | None = None
    behavior_type: str
    content: str | None = None
    result: str | None = None
    duration_seconds: int | None = None
    source: str | None = None


@router.get("")
def list_behaviors(
    limit: int = Query(50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询学习行为：学生只能查自己（文档 Section 19.10）"""
    student_id = current_user.id
    behaviors = behavior_service.get_behaviors(db, student_id, limit)
    return [
        {
            "id": b.id,
            "student_id": b.student_id,
            "course_id": b.course_id,
            "knowledge_point_id": b.knowledge_point_id,
            "behavior_type": b.behavior_type,
            "content": b.content,
            "result": b.result,
            "duration_seconds": b.duration_seconds,
            "source": b.source,
            "created_at": b.created_at.isoformat(),
        }
        for b in behaviors
    ]


@router.post("")
def create_behavior(
    req: BehaviorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建学习行为：使用 current_user.id，校验课程可访问（文档 Section 19.10）"""
    student_id = current_user.id

    # 如果有 course_id，校验课程可访问
    if req.course_id:
        course_permission_service.require_view_course(db, current_user, req.course_id)

    behavior = behavior_service.record(
        db=db,
        student_id=student_id,
        course_id=req.course_id,
        knowledge_point_id=req.knowledge_point_id,
        behavior_type=req.behavior_type,
        content=req.content,
        result=req.result,
        duration_seconds=req.duration_seconds,
        source=req.source,
    )
    if req.behavior_type == "view_resource" and req.course_id and req.knowledge_point_id:
        profile_service.increase_resource_view(
            db,
            student_id,
            req.course_id,
            req.knowledge_point_id,
        )
        profile_service.refresh_point_mastery(
            db,
            student_id,
            req.course_id,
            req.knowledge_point_id,
        )
    db.commit()
    db.refresh(behavior)
    return {
        "id": behavior.id,
        "student_id": behavior.student_id,
        "course_id": behavior.course_id,
        "knowledge_point_id": behavior.knowledge_point_id,
        "behavior_type": behavior.behavior_type,
        "content": behavior.content,
        "result": behavior.result,
        "duration_seconds": behavior.duration_seconds,
        "source": behavior.source,
        "created_at": behavior.created_at.isoformat(),
    }
