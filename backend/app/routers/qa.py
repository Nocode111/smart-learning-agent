from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.qa import AskRequest, AskResponse, FeedbackRequest, QARecordResponse
from app.services.qa_agent_service import get_qa_agent_service
from app.services.course_permission_service import course_permission_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
def ask_question(
    req: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """答疑接口：使用 current_user.id，校验课程访问权（文档 Section 17 / 19.5）"""
    # 安全修正：使用 JWT 中的用户 ID，不信任请求体
    student_id = current_user.id
    # 校验课程访问权限
    course_permission_service.require_view_course(db, current_user, req.course_id)

    qa_service = get_qa_agent_service()
    return qa_service.ask(
        db=db,
        student_id=student_id,
        course_id=req.course_id,
        question=req.question,
    )


@router.get("/history", response_model=list[QARecordResponse])
def get_history(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """答疑历史：学生只能查自己的历史（文档 Section 17 / 19.5）"""
    # 安全修正：使用 JWT 中的用户 ID
    student_id = current_user.id
    # 校验课程访问权限
    course_permission_service.require_view_course(db, current_user, course_id)

    qa_service = get_qa_agent_service()
    return qa_service.get_history(db, student_id, course_id)


@router.post("/{qa_id}/feedback", response_model=QARecordResponse)
def submit_feedback(
    qa_id: int,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交反馈：校验 QA 记录属于当前用户（文档 Section 19.5）"""
    qa_service = get_qa_agent_service()

    # 校验 QA 记录属于当前用户
    from app.models.qa_record import QARecord
    qa = db.query(QARecord).filter(QARecord.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=404, detail="答疑记录不存在")
    if qa.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作该答疑记录")

    try:
        return qa_service.submit_feedback(db, qa_id, req.resolved, req.comment)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
