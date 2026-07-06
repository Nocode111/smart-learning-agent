"""
提问任务路由 — 创建任务、查询任务、取消任务、SSE 事件流。

文档参考：docs/智能答疑真实流式回答SSE方案_详细技术实现文档.md Section 6
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models.user import User
from app.schemas.agent import (
    AgentChatTaskCancelRequest,
    AgentChatTaskCancelResponse,
    AgentChatTaskRequest,
    AgentChatTaskResponse,
    AgentChatTaskStatusResponse,
)
from app.security import get_current_user
from app.services.agent_chat_task_service import agent_chat_task_service
from app.services.agent_chat_task_runner import agent_chat_task_runner

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=AgentChatTaskResponse)
def create_task(
    req: AgentChatTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建提问任务（文档 Section 10.1）"""
    try:
        task = agent_chat_task_service.create_task(
            db=db,
            current_user=current_user,
            course_id=req.course_id,
            conversation_id=req.conversation_id,
            message=req.message,
            attachment_ids=req.attachment_ids,
            client_request_id=req.client_request_id,
        )
        return AgentChatTaskResponse(
            task_uuid=task.task_uuid,
            conversation_id=task.conversation_id,
            user_message={
                "id": task.user_message_id,
                "role": "user",
                "content": task.request_message,
                "status": "completed",
            },
            assistant_message={
                "id": task.assistant_message_id,
                "role": "assistant",
                "content": "",
                "message_type": "answer",
                "status": "pending",
            },
            status=task.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{task_uuid}", response_model=AgentChatTaskStatusResponse)
def get_task(
    task_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询任务状态（文档 Section 10.2）"""
    try:
        task = agent_chat_task_service.get_task_or_404(db, task_uuid, current_user.id)
        return AgentChatTaskStatusResponse(
            task_uuid=task.task_uuid,
            status=task.status,
            stage=task.stage,
            progress_text=task.progress_text,
            conversation_id=task.conversation_id,
            user_message_id=task.user_message_id,
            assistant_message_id=task.assistant_message_id,
            cancel_requested=bool(task.cancel_requested),
            error_message=task.error_message,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{task_uuid}/events")
async def task_events(
    task_uuid: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """SSE 事件流 — 边执行边推送，真流式（文档 Section 6.2）

    注意：使用 URL 参数 token 进行认证（浏览器 EventSource 不支持自定义 Header）。
    """
    from app.security import verify_token

    try:
        payload = verify_token(token)
        student_id = payload.get("user_id")
    except Exception:
        raise HTTPException(status_code=401, detail="认证失败")

    task = agent_chat_task_service.get_task(db, task_uuid)
    if not task or task.student_id != student_id:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        """实时事件生成器 — 使用 asyncio.Queue + emit 回调实现真流式"""
        queue = asyncio.Queue()

        async def emit(event_type: str, data: dict):
            """实时推送事件到队列（文档 Section 6.2）"""
            await queue.put({
                "event": event_type,
                "data": data,
            })

        async def run():
            """后台执行任务，通过 emit 实时推送事件"""
            try:
                await agent_chat_task_runner.run_task(
                    task_uuid=task_uuid,
                    emit=emit,
                )
            except Exception as exc:
                logger.exception("任务执行异常: %s", task_uuid)
                await emit("task_failed", {"error": str(exc)})
            finally:
                await queue.put(None)  # sentinel，标记结束

        runner_task = asyncio.create_task(run())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield {
                    "event": item["event"],
                    "data": json.dumps(item["data"], ensure_ascii=False),
                }
        finally:
            # 浏览器主动断开 SSE 连接 ≠ 用户点击停止。
            # 用户停止必须走 POST /cancel 接口。
            # 这里保留 runner 继续执行，不强制取消。
            if not runner_task.done():
                logger.info("SSE 连接断开，但任务 %s 继续后台执行", task_uuid)

    return EventSourceResponse(event_generator())


@router.post("/{task_uuid}/cancel", response_model=AgentChatTaskCancelResponse)
def cancel_task(
    task_uuid: str,
    req: AgentChatTaskCancelRequest = AgentChatTaskCancelRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消任务（文档 Section 10.4）"""
    try:
        task = agent_chat_task_service.request_cancel(
            db=db,
            task_uuid=task_uuid,
            student_id=current_user.id,
            reason=req.reason,
        )
        return AgentChatTaskCancelResponse(
            ok=True,
            task_uuid=task_uuid,
            status=task.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
