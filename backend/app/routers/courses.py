from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.course import (
    CourseCreate,
    CourseUpdate,
    CourseResponse,
    StudentCourseCreate,
    CourseOutlineGenerateRequest,
    CourseOutlineGenerateResponse,
)
from app.services.course_service import course_service
from app.services.course_permission_service import course_permission_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("", response_model=list[CourseResponse])
def list_courses(
    scope: str = Query("available"),
    courseType: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """课程列表，支持 scope 和 courseType 过滤（文档 Section 8.1）"""
    return course_service.get_available_courses(db, current_user, scope=scope, course_type=courseType)


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取课程详情，校验访问权限"""
    course = course_permission_service.require_view_course(db, current_user, course_id)
    return course


@router.post("", response_model=CourseResponse)
def create_course(
    req: CourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """教师创建课程（文档 Section 8.2）"""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="只有教师和管理员可以创建课程")
    return course_service.create_teacher_course(
        db=db,
        user=current_user,
        name=req.name,
        description=req.description,
    )


@router.post("/student", response_model=CourseResponse)
def create_student_course(
    req: StudentCourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """学生创建自建课程（文档 Section 8.3）"""
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以创建自建课程")
    return course_service.create_student_course(
        db=db,
        user=current_user,
        name=req.name,
        description=req.description,
        learning_goal=req.learning_goal,
        auto_generate_outline=req.auto_generate_outline,
    )


@router.put("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: int,
    req: CourseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新课程，校验管理权限（文档 Section 8.4）"""
    course_permission_service.require_manage_course(db, current_user, course_id)
    try:
        return course_service.update_course(db, course_id, name=req.name, description=req.description)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{course_id}")
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除课程（文档 Section 8.5）"""
    course_permission_service.require_manage_course(db, current_user, course_id)
    try:
        course_service.soft_delete_course(db, course_id)
        return {"message": "课程已删除"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{course_id}/outline/generate", response_model=CourseOutlineGenerateResponse)
def generate_course_outline(
    course_id: int,
    req: CourseOutlineGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 生成知识点大纲（文档 Section 9.5）"""
    course_permission_service.require_manage_course(db, current_user, course_id)

    # 如果 overwrite_existing 且是学生课程，允许覆盖（仅限自己的课程）
    if req.overwrite_existing and current_user.role != "admin":
        course = course_service.get_course(db, course_id)
        if course and course.course_type == "student" and course.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="无权覆盖该课程的知识点")

    from app.services.course_outline_service import course_outline_service

    try:
        points = course_outline_service.generate_outline(
            db=db,
            course_id=course_id,
            learning_goal=req.learning_goal,
            overwrite_existing=req.overwrite_existing,
        )
        return CourseOutlineGenerateResponse(
            course_id=course_id,
            knowledge_points=points,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"大纲生成失败：{str(e)}")
