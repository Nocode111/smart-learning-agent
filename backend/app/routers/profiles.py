from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.profile import ProfileResponse
from app.services.profile_service import profile_service
from app.services.course_permission_service import course_permission_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("", response_model=ProfileResponse)
def get_profile(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取学习画像：学生只能查自己的画像，课程必须可访问（文档 Section 13.1 / 19.7）"""
    student_id = current_user.id
    course_permission_service.require_view_course(db, current_user, course_id)

    profile = profile_service.get_profile_for_agent(db, student_id, course_id)
    student_profile = profile_service.get_or_create_profile(db, student_id, course_id)
    return ProfileResponse(
        student_id=student_id,
        course_id=course_id,
        overall_level=profile.get("overall_level"),
        knowledge_mastery=profile.get("knowledge_mastery", []),
        weak_points=profile.get("weak_points", []),
        updated_at=student_profile.updated_at,
    )


@router.post("/refresh", response_model=ProfileResponse)
def refresh_profile(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """刷新学习画像：学生只能刷新自己的画像（文档 Section 19.7）"""
    student_id = current_user.id
    course_permission_service.require_view_course(db, current_user, course_id)

    profile_service.update_profile(db, student_id, course_id)
    profile = profile_service.get_profile_for_agent(db, student_id, course_id)
    student_profile = profile_service.get_or_create_profile(db, student_id, course_id)
    return ProfileResponse(
        student_id=student_id,
        course_id=course_id,
        overall_level=profile.get("overall_level"),
        knowledge_mastery=profile.get("knowledge_mastery", []),
        weak_points=profile.get("weak_points", []),
        updated_at=student_profile.updated_at,
    )


@router.get("/weak-points")
def get_weak_points(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取薄弱知识点：学生只能查自己的（文档 Section 19.7）"""
    student_id = current_user.id
    course_permission_service.require_view_course(db, current_user, course_id)
    return profile_service.get_weak_points(db, student_id, course_id)
