from datetime import datetime
from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    student_id: int | None = None
    course_id: int
    message: str
    conversation_id: int | None = None
    attachment_ids: list[int] = Field(default_factory=list)


class AgentDocumentPayload(BaseModel):
    id: int
    title: str
    file_name: str
    preview_content: str | None = None
    download_url: str


class AgentChatResponse(BaseModel):
    conversation_id: int
    intent: str
    type: str
    text: str
    qa_id: int | None = None
    document: AgentDocumentPayload | None = None
    agent_steps: list[dict] = Field(default_factory=list)
    retrieved_chunks: list[dict] = Field(default_factory=list)
    pending_action: dict | None = None   # 文档 Section 19.3 / 20.2
    debug_intent: dict | None = None     # 文档 Section 19.2 / 20.2
    practice_session: dict | None = None  # 对话式练习 Session 信息
    practice_result: dict | None = None   # 对话式练习批改结果
    attachments: list[dict] = Field(default_factory=list)  # 本轮引用的附件


class AgentConversationResponse(BaseModel):
    id: int
    student_id: int
    course_id: int
    title: str | None = None
    status: str
    last_topic: str | None = None
    message_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentMessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    message_type: str
    content: str | None = None
    intent: str | None = None
    qa_id: int | None = None
    document_id: int | None = None
    related_knowledge_point_ids: list[int] | None = None
    agent_steps_json: list[dict] | None = None
    retrieved_chunks_json: list[dict] | None = None
    metadata_json: dict | None = None
    # 二期：消息状态字段
    status: str = "completed"
    task_id: int | None = None
    client_request_id: str | None = None
    canceled_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── 二期：提问任务 schemas ──────────────────────────────────

class AgentChatTaskRequest(BaseModel):
    course_id: int
    conversation_id: int | None = None
    message: str
    attachment_ids: list[int] = Field(default_factory=list)
    client_request_id: str


class AgentChatTaskResponse(BaseModel):
    task_uuid: str
    conversation_id: int
    user_message: dict
    assistant_message: dict
    status: str


class AgentChatTaskStatusResponse(BaseModel):
    task_uuid: str
    status: str
    stage: str | None = None
    progress_text: str | None = None
    conversation_id: int
    user_message_id: int
    assistant_message_id: int | None = None
    cancel_requested: bool = False
    error_message: str | None = None


class AgentChatTaskCancelRequest(BaseModel):
    reason: str = "user_stop"


class AgentChatTaskCancelResponse(BaseModel):
    ok: bool = True
    task_uuid: str
    status: str
