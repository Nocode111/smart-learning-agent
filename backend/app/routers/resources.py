import os
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.resource import ResourceCreate, ResourceResponse
from app.services.resource_service import resource_service
from app.services.course_permission_service import course_permission_service
from app.services.document_extract_service import document_extract_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()

# 文件上传限制
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.get("", response_model=list[ResourceResponse])
def list_resources(
    course_id: int = Query(..., alias="courseId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询资源，校验课程访问权限（文档 Section 15）"""
    course_permission_service.require_view_course(db, current_user, course_id)
    return resource_service.get_resources(db, course_id)


@router.post("", response_model=ResourceResponse)
def create_resource(
    req: ResourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建资源（文本录入），校验课程管理权限（文档 Section 15）"""
    course_permission_service.require_manage_course(db, current_user, req.course_id)
    return resource_service.create_resource(
        db=db,
        course_id=req.course_id,
        knowledge_point_id=req.knowledge_point_id,
        title=req.title,
        resource_type=req.resource_type,
        content=req.content,
        file_url=req.file_url,
        owner_id=current_user.id,
    )


@router.post("/upload", response_model=ResourceResponse)
def upload_resource(
    course_id: int = Form(...),
    knowledge_point_id: int | None = Form(None),
    title: str = Form(...),
    file: UploadFile = File(...),
    auto_index: bool = Form(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文件资源（文档 Section 10.4）

    流程：
    1. 校验用户对课程有管理权限
    2. 校验文件类型和大小
    3. 保存文件
    4. 抽取文本
    5. 创建 learning_resources 记录
    6. 如果 auto_index=true，调用索引服务
    """
    course_permission_service.require_manage_course(db, current_user, course_id)

    # 校验文件类型
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")
    if not document_extract_service.is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。允许的类型：{', '.join(document_extract_service.ALLOWED_SUFFIXES)}",
        )

    # 读取文件内容
    file_content = file.file.read()

    # 校验文件大小
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")

    # 保存文件
    file_path, safe_name, file_size = resource_service.save_upload_file(
        file_content, file.filename, course_id
    )

    # 确定资源类型
    suffix = os.path.splitext(file.filename)[1].lower()
    mime_type = document_extract_service.get_mime_type(file.filename)
    if suffix in (".txt", ".md"):
        resource_type = "text"
    elif suffix == ".pdf":
        resource_type = "pdf"
    elif suffix == ".docx":
        resource_type = "docx"
    elif suffix == ".pptx":
        resource_type = "pptx"
    else:
        resource_type = "file"

    # 抽取文本
    content = None
    index_status = "none"
    index_error = None
    try:
        content = document_extract_service.extract_text(file_path, mime_type, safe_name)
    except Exception as e:
        index_error = f"文本抽取失败：{str(e)}"

    # 创建资源记录
    from app.models.resource import LearningResource
    from datetime import datetime

    resource = LearningResource(
        course_id=course_id,
        knowledge_point_id=knowledge_point_id,
        title=title,
        resource_type=resource_type,
        content=content,
        file_name=safe_name,
        file_path=file_path,
        file_size=file_size,
        mime_type=mime_type,
        owner_id=current_user.id,
        indexed=0,
        index_status="none",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # 自动索引
    if auto_index and content:
        try:
            resource_service.index_resource(db, resource.id)
            db.refresh(resource)
        except Exception:
            pass

    return resource


@router.get("/{resource_id}", response_model=ResourceResponse)
def get_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取资源详情，校验课程访问权限"""
    resource = resource_service.get_resource(db, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")
    # 通过所属课程校验访问权
    course_permission_service.require_view_course(db, current_user, resource.course_id)
    return resource


@router.post("/{resource_id}/index", response_model=ResourceResponse)
def index_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """索引资源，校验课程管理权限（文档 Section 15）"""
    resource = resource_service.get_resource(db, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")
    course_permission_service.require_manage_course(db, current_user, resource.course_id)

    try:
        return resource_service.index_resource(db, resource_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{resource_id}")
def delete_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除资源，校验课程管理权限（文档 Section 15）"""
    resource = resource_service.get_resource(db, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")
    course_permission_service.require_manage_course(db, current_user, resource.course_id)

    try:
        resource_service.delete_resource(db, resource_id)
        return {"message": "资源已删除"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
