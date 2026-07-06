from pydantic import BaseModel
from datetime import datetime


class ResourceCreate(BaseModel):
    course_id: int
    knowledge_point_id: int | None = None
    title: str
    resource_type: str = "text"
    content: str | None = None
    file_url: str | None = None


class ResourceResponse(BaseModel):
    id: int
    course_id: int
    knowledge_point_id: int | None = None
    title: str
    resource_type: str
    content: str | None = None
    file_url: str | None = None
    owner_id: int | None = None
    file_name: str | None = None
    file_path: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    indexed: int
    index_status: str = "none"
    index_error: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
