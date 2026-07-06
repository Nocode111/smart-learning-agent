from datetime import datetime

from pydantic import BaseModel, Field


class AgentAttachmentResponse(BaseModel):
    id: int
    conversation_id: int
    course_id: int
    title: str
    original_file_name: str
    stored_file_name: str
    file_ext: str
    file_size: int
    mime_type: str | None = None
    attachment_type: str
    extract_status: str
    index_status: str
    index_error: str | None = None
    chunk_count: int = 0
    status: str
    # 二期：附件移除字段
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    delete_reason: str | None = None
    delete_error: str | None = None
    physical_file_deleted: int = 0
    delete_message_id: int | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentAttachmentUploadResponse(BaseModel):
    conversation_id: int
    attachment: AgentAttachmentResponse
    message: dict | None = None


class AgentAttachmentListResponse(BaseModel):
    items: list[AgentAttachmentResponse] = Field(default_factory=list)


class AgentAttachmentPreviewResponse(BaseModel):
    id: int
    title: str
    content_preview: str
    extract_status: str
    index_status: str


class AgentAttachmentRemoveRequest(BaseModel):
    delete_physical_file: bool = False
    reason: str = "user_removed"


class AgentAttachmentRemoveResponse(BaseModel):
    ok: bool = True
    attachment: AgentAttachmentResponse
    message: dict | None = None
    already_removed: bool = False
