from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.question import QuestionCreate, QuestionResponse, SubmitAnswerRequest, SubmitAnswerResponse
from app.services.question_service import question_service
from app.services.course_permission_service import course_permission_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("", response_model=list[QuestionResponse])
def list_questions(
    course_id: int = Query(..., alias="courseId"),
    knowledge_point_id: int | None = Query(None, alias="knowledgePointId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询题目，校验课程访问权限（文档 Section 16）"""
    course_permission_service.require_view_course(db, current_user, course_id)
    return question_service.get_questions(db, course_id, knowledge_point_id)


@router.post("", response_model=QuestionResponse)
def create_question(
    req: QuestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建题目，校验课程管理权限（文档 Section 16）

    - 教师课程：只允许 teacher/admin 管理。
    - 学生课程：允许课程 owner 学生创建题目。
    """
    course_permission_service.require_manage_course(db, current_user, req.course_id)
    return question_service.create_question(
        db=db,
        course_id=req.course_id,
        knowledge_point_id=req.knowledge_point_id,
        question_type=req.question_type,
        stem=req.stem,
        options_json=req.options_json,
        answer=req.answer,
        explanation=req.explanation,
        difficulty=req.difficulty,
    )


@router.post("/{question_id}/submit", response_model=SubmitAnswerResponse)
def submit_answer(
    question_id: int,
    req: SubmitAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交答案：使用 current_user.id，校验题目所属课程可访问（文档 Section 16）"""
    from app.models.question import Question

    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    # 校验题目所属课程可访问
    course_permission_service.require_view_course(db, current_user, question.course_id)

    try:
        return question_service.submit_answer(
            db=db,
            student_id=current_user.id,
            question_id=question_id,
            submitted_answer=req.answer,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
