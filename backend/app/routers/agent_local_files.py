"""
本地文件修改 API 路由（文档 Section 12）

前缀：/api/agent/local-files
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.agent_local_file import (
    LocalFileCancelRequest,
    LocalFileConfigResponse,
    LocalFileConfirmRequest,
    LocalFileOperationResponse,
    LocalFileRestoreRequest,
)
from app.security import get_current_user
from app.services.agent_local_file_edit_service import agent_local_file_edit_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ── 12.1 查询操作详情 ──────────────────────────────────────

@router.get("/operations/{operation_uuid}")
def get_operation(
    operation_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询本地文件修改操作详情"""
    try:
        result = agent_local_file_edit_service.get_operation(
            db=db,
            operation_uuid=operation_uuid,
            student_id=current_user.id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 12.2 确认修改 ──────────────────────────────────────────

@router.post("/operations/{operation_uuid}/confirm")
def confirm_operation(
    operation_uuid: str,
    req: LocalFileConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认写入本地文件（文档 Section 11.5）"""
    try:
        result = agent_local_file_edit_service.confirm_operation(
            db=db,
            operation_uuid=operation_uuid,
            student_id=current_user.id,
            expected_original_sha256=req.expected_original_sha256,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 12.3 取消修改 ──────────────────────────────────────────

@router.post("/operations/{operation_uuid}/cancel")
def cancel_operation(
    operation_uuid: str,
    req: LocalFileCancelRequest = LocalFileCancelRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消修改预览（文档 Section 11.6）"""
    try:
        result = agent_local_file_edit_service.cancel_operation(
            db=db,
            operation_uuid=operation_uuid,
            student_id=current_user.id,
            reason=req.reason or "user_cancel",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 12.4 恢复备份 ──────────────────────────────────────────

@router.post("/operations/{operation_uuid}/restore")
def restore_operation(
    operation_uuid: str,
    req: LocalFileRestoreRequest = LocalFileRestoreRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复备份（文档 Section 11.7）"""
    try:
        result = agent_local_file_edit_service.restore_operation(
            db=db,
            operation_uuid=operation_uuid,
            student_id=current_user.id,
            expected_current_sha256=req.expected_current_sha256,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 12.5 查看功能配置 ──────────────────────────────────────

@router.get("/config", response_model=LocalFileConfigResponse)
def get_config():
    """返回当前本地文件修改功能配置"""
    return agent_local_file_edit_service.get_config()
