"""
本地文件修改操作 Pydantic Schema（文档 Section 9）
"""

from pydantic import BaseModel


class LocalFileOperationResponse(BaseModel):
    operation_uuid: str
    status: str
    file_name: str
    file_ext: str
    display_path: str
    file_size: int
    instruction: str
    summary: str | None = None
    original_sha256: str
    proposed_sha256: str | None = None
    diff_text: str | None = None
    error_message: str | None = None


class LocalFileConfirmRequest(BaseModel):
    expected_original_sha256: str


class LocalFileCancelRequest(BaseModel):
    reason: str | None = "user_cancel"


class LocalFileRestoreRequest(BaseModel):
    expected_current_sha256: str | None = None


class LocalFileConfigResponse(BaseModel):
    enabled: bool
    allowed_roots: list[str]
    allowed_extensions: list[str]
    max_size_bytes: int
