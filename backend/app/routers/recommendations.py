from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.recommendation import PlanResponse, TaskResponse, GenerateRequest
from app.services.recommendation_service import recommendation_service
from app.services.course_permission_service import course_permission_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("", response_model=list[PlanResponse])
def list_plans(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """推荐方案列表：学生只能查自己的，课程必须可访问（文档 Section 13.3 / 19.8）"""
    student_id = current_user.id
    course_permission_service.require_view_course(db, current_user, course_id)

    plans = recommendation_service.get_plans(db, student_id, course_id)
    result = []
    for plan in plans:
        tasks = recommendation_service.get_tasks(db, plan.id)
        result.append(
            PlanResponse(
                id=plan.id,
                student_id=plan.student_id,
                course_id=plan.course_id,
                title=plan.title,
                reason=plan.reason,
                status=plan.status,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
                tasks=[TaskResponse.model_validate(t) for t in tasks],
            )
        )
    return result


@router.post("/generate", response_model=PlanResponse)
def generate_plan(
    req: GenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成推荐方案：使用 current_user.id，校验课程可访问（文档 Section 19.8）"""
    student_id = current_user.id
    course_permission_service.require_view_course(db, current_user, req.course_id)

    plan = recommendation_service.generate_for_weak_point(
        db=db,
        student_id=student_id,
        course_id=req.course_id,
        knowledge_point_id=req.knowledge_point_id,
    )
    if not plan:
        raise HTTPException(status_code=400, detail="无法生成推荐方案，请检查知识点是否存在")

    tasks = recommendation_service.get_tasks(db, plan.id)
    return PlanResponse(
        id=plan.id,
        student_id=plan.student_id,
        course_id=plan.course_id,
        title=plan.title,
        reason=plan.reason,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        tasks=[TaskResponse.model_validate(t) for t in tasks],
    )


@router.post("/{plan_id}/tasks/{task_id}/complete", response_model=TaskResponse)
def complete_task(
    plan_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成任务：校验 plan 属于当前用户（文档 Section 19.8）"""
    from app.models.recommendation_plan import RecommendationPlan

    plan = db.query(RecommendationPlan).filter(RecommendationPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="推荐方案不存在")
    if plan.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作该推荐方案")

    try:
        task = recommendation_service.complete_task(db, task_id)
        return TaskResponse.model_validate(task)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
