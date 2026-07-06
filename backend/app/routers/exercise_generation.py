from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.generated_exercise_document import GeneratedExerciseDocument
from app.models.user import User
from app.schemas.exercise_generation import ExerciseGenerateRequest, ExerciseGenerateResponse
from app.security import get_current_user
from app.services.exercise_agent_service import exercise_agent_service
from app.services.course_permission_service import course_permission_service

router = APIRouter()


@router.post("/generate", response_model=ExerciseGenerateResponse)
def generate_exercise_document(
    req: ExerciseGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 校验课程访问权限（文档 Section 12.4 / 19.9）
    course_permission_service.require_view_course(db, current_user, req.course_id)
    try:
        doc, agent_steps = exercise_agent_service.generate(
            db=db,
            user_id=current_user.id,
            course_id=req.course_id,
            prompt=req.prompt,
            question_count=req.question_count,
            knowledge_point_id=req.knowledge_point_id,
            difficulty=req.difficulty,
            include_answer=req.include_answer,
            include_explanation=req.include_explanation,
        )
        return ExerciseGenerateResponse(
            id=doc.id,
            title=doc.title,
            file_name=doc.file_name,
            preview_content=doc.preview_content,
            download_url=f"/api/exercise-generation/{doc.id}/download",
            agent_steps=agent_steps,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/documents")
def list_documents(
    course_id: int | None = Query(None, alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(GeneratedExerciseDocument).filter(
        GeneratedExerciseDocument.user_id == current_user.id
    )
    if course_id:
        query = query.filter(GeneratedExerciseDocument.course_id == course_id)
    return query.order_by(GeneratedExerciseDocument.created_at.desc()).all()


@router.get("/documents/{document_id}")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(GeneratedExerciseDocument).filter(
        GeneratedExerciseDocument.id == document_id,
        GeneratedExerciseDocument.user_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(GeneratedExerciseDocument).filter(
        GeneratedExerciseDocument.id == document_id,
        GeneratedExerciseDocument.user_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    return FileResponse(
        path=doc.file_path,
        filename=doc.file_name,
        media_type="text/markdown",
    )
