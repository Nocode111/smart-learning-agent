from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.course import KnowledgePointCreate, KnowledgePointUpdate, KnowledgePointResponse
from app.services.knowledge_point_service import knowledge_point_service
from app.services.course_permission_service import course_permission_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("", response_model=list[KnowledgePointResponse])
def list_knowledge_points(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询知识点，校验课程访问权限（文档 Section 14）"""
    course_permission_service.require_view_course(db, current_user, course_id)
    return knowledge_point_service.get_points(db, course_id)


@router.post("", response_model=KnowledgePointResponse)
def create_knowledge_point(
    req: KnowledgePointCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建知识点，校验课程管理权限（文档 Section 14）

    - teacher/admin 可以给自己管理的教师课程创建。
    - student 可以给自己创建的学生课程创建。
    """
    course_permission_service.require_manage_course(db, current_user, req.course_id)
    return knowledge_point_service.create_point(
        db=db,
        course_id=req.course_id,
        parent_id=req.parent_id,
        name=req.name,
        description=req.description,
        difficulty=req.difficulty,
        sort_order=req.sort_order,
    )


@router.put("/{point_id}", response_model=KnowledgePointResponse)
def update_knowledge_point(
    point_id: int,
    req: KnowledgePointUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新知识点：先查知识点，再查所属课程，校验管理权限（文档 Section 14）"""
    point = knowledge_point_service.get_point(db, point_id)
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")
    course_permission_service.require_manage_course(db, current_user, point.course_id)

    try:
        return knowledge_point_service.update_point(
            db, point_id,
            name=req.name, description=req.description,
            difficulty=req.difficulty, sort_order=req.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{point_id}")
def delete_knowledge_point(
    point_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除知识点：先查知识点，再查所属课程，校验管理权限（文档 Section 14）"""
    point = knowledge_point_service.get_point(db, point_id)
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")
    course_permission_service.require_manage_course(db, current_user, point.course_id)

    try:
        knowledge_point_service.delete_point(db, point_id)
        return {"message": "知识点已删除"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
