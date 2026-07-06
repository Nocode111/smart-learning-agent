"""
对话附件路由 — 上传、列表、预览、下载、删除、重建索引。

文档参考：docs/智能答疑对话附件系统方案_详细技术实现文档.md Section 12
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.agent_attachment import (
    AgentAttachmentListResponse,
    AgentAttachmentPreviewResponse,
    AgentAttachmentRemoveRequest,
    AgentAttachmentRemoveResponse,
    AgentAttachmentResponse,
    AgentAttachmentUploadResponse,
)
from app.security import get_current_user
from app.services.agent_attachment_service import agent_attachment_service
from app.services.course_permission_service import course_permission_service

router = APIRouter()


@router.post("/upload", response_model=AgentAttachmentUploadResponse)
def upload_attachment(
    course_id: int = Form(...),
    conversation_id: int | None = Form(None),
    title: str | None = Form(None),
    auto_index: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传对话附件（文档 Section 12.1）"""
    try:
        # 校验课程访问权限（学生也可上传，使用 view 权限而非 manage）
        course_permission_service.require_view_course(db, current_user, course_id)

        # 如果传了 conversation_id，校验归属
        if conversation_id:
            from app.services.agent_conversation_service import agent_conversation_service
            conversation = agent_conversation_service.get_conversation_by_id(
                db=db,
                student_id=current_user.id,
                conversation_id=conversation_id,
            )

        result = agent_attachment_service.upload_attachment(
            db=db,
            student_id=current_user.id,
            course_id=course_id,
            conversation_id=conversation_id,
            file=file,
            title=title,
            auto_index=auto_index,
        )

        attachment = result["attachment"]
        upload_message = result["upload_message"]

        return AgentAttachmentUploadResponse(
            conversation_id=result["conversation"].id,
            attachment=AgentAttachmentResponse.model_validate(attachment),
            message={
                "role": upload_message.role,
                "message_type": upload_message.message_type,
                "content": upload_message.content,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=AgentAttachmentListResponse)
def list_attachments(
    conversation_id: int = Query(..., alias="conversationId"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询当前会话附件（文档 Section 12.2）"""
    try:
        from app.services.agent_conversation_service import agent_conversation_service

        # 校验会话归属
        conversation = agent_conversation_service.get_conversation_by_id(
            db=db,
            student_id=current_user.id,
            conversation_id=conversation_id,
        )
        # 校验课程访问权限
        course_permission_service.require_view_course(db, current_user, conversation.course_id)

        attachments = agent_attachment_service.list_active_attachments(
            db=db,
            conversation_id=conversation_id,
            student_id=current_user.id,
            course_id=conversation.course_id,
        )
        return AgentAttachmentListResponse(
            items=[AgentAttachmentResponse.model_validate(a) for a in attachments]
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{attachment_id}/preview", response_model=AgentAttachmentPreviewResponse)
def preview_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """附件文本预览（文档 Section 12.3）"""
    attachment = agent_attachment_service.get_attachment(
        db=db,
        attachment_id=attachment_id,
        student_id=current_user.id,
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="附件不存在或无权访问")
    if attachment.status == "removed":
        raise HTTPException(status_code=410, detail="附件已移除")

    # 校验课程访问权限
    course_permission_service.require_view_course(db, current_user, attachment.course_id)

    content_preview = (attachment.content or "")[:500]
    return AgentAttachmentPreviewResponse(
        id=attachment.id,
        title=attachment.title,
        content_preview=content_preview,
        extract_status=attachment.extract_status,
        index_status=attachment.index_status,
    )


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载附件原文件（文档 Section 12.4）"""
    import os

    attachment = agent_attachment_service.get_attachment(
        db=db,
        attachment_id=attachment_id,
        student_id=current_user.id,
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="附件不存在或无权访问")
    if attachment.status == "removed":
        raise HTTPException(status_code=410, detail="附件已移除")

    # 校验课程访问权限
    course_permission_service.require_view_course(db, current_user, attachment.course_id)

    file_path = attachment.file_path
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在或已被删除")

    return FileResponse(
        path=file_path,
        filename=attachment.original_file_name,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除附件（文档 Section 12.5）"""
    try:
        agent_attachment_service.delete_attachment(
            db=db,
            attachment_id=attachment_id,
            student_id=current_user.id,
        )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{attachment_id}/remove", response_model=AgentAttachmentRemoveResponse)
def remove_attachment(
    attachment_id: int,
    req: AgentAttachmentRemoveRequest = AgentAttachmentRemoveRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除附件（二期完整版，文档 Section 7.1）"""
    try:
        result = agent_attachment_service.remove_attachment(
            db=db,
            attachment_id=attachment_id,
            student_id=current_user.id,
            delete_physical_file=req.delete_physical_file,
            reason=req.reason,
        )
        return AgentAttachmentRemoveResponse(
            ok=True,
            attachment=AgentAttachmentResponse.model_validate(result["attachment"]),
            message={
                "id": result["message"].id,
                "message_type": result["message"].message_type,
                "content": result["message"].content,
            } if result["message"] else None,
            already_removed=result.get("already_removed", False),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{attachment_id}/reindex")
def reindex_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重建附件索引（文档 Section 12.6）"""
    try:
        attachment_check = agent_attachment_service.get_attachment(
            db=db,
            attachment_id=attachment_id,
            student_id=current_user.id,
        )
        if not attachment_check:
            raise HTTPException(status_code=404, detail="附件不存在或无权访问")
        if attachment_check.status == "removed":
            raise HTTPException(status_code=410, detail="附件已移除")

        attachment = agent_attachment_service.reindex_attachment(
            db=db,
            attachment_id=attachment_id,
            student_id=current_user.id,
        )
        return AgentAttachmentResponse.model_validate(attachment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
