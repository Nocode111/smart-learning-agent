"""
长期目标守护 API 路由（文档 Section 13）

挂载前缀：/api/agent/goals（复用 agent_goals 路由前缀）
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.user import User
from app.models.agent_goal_guardian import (
    AgentGoalGuardianConfig,
    AgentGoalGuardianRun,
    AgentGoalGuardianEvent,
)
from app.schemas.agent_goal_guardian import (
    AgentGoalGuardianConfigResponse,
    AgentGoalGuardianConfigUpdateRequest,
    AgentGoalGuardianRunResponse,
    AgentGoalGuardianRunTriggerResponse,
    AgentGoalGuardianEventResponse,
)
from app.security import get_current_user
from app.services.course_permission_service import course_permission_service
from app.services.agent_goal_service import agent_goal_service
from app.services.agent_goal_guardian_service import agent_goal_guardian_service
from app.utils.time_utils import now_shanghai

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_goal_guardian_and_check(db: Session, goal_id: int, current_user: User):
    """获取目标并校验权限"""
    goal = agent_goal_service._get_goal_for_user(db, goal_id, current_user.id)
    course_permission_service.require_view_course(db, current_user, goal.course_id)
    return goal


# ── 13.1 获取守护配置 ──────────────────────────────────────────

@router.get("/{goal_id}/guardian/config", response_model=AgentGoalGuardianConfigResponse)
def get_guardian_config(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取目标守护配置（文档 Section 13.1）"""
    goal = _get_goal_guardian_and_check(db, goal_id, current_user)

    config = agent_goal_guardian_service.ensure_config_for_goal(db, goal)

    return AgentGoalGuardianConfigResponse(
        goal_id=config.goal_id,
        enabled=bool(config.enabled),
        guard_level=config.guard_level,
        check_interval_minutes=config.check_interval_minutes,
        stale_action_hours=config.stale_action_hours,
        due_soon_days=config.due_soon_days,
        progress_lag_threshold=float(config.progress_lag_threshold),
        low_quality_threshold=float(config.low_quality_threshold),
        allow_auto_prepare=bool(config.allow_auto_prepare),
        allow_auto_remedial=bool(config.allow_auto_remedial),
        allow_auto_replan_suggestion=bool(config.allow_auto_replan_suggestion),
        last_checked_at=config.last_checked_at,
        next_check_at=config.next_check_at,
    )


# ── 13.2 更新守护配置 ──────────────────────────────────────────

@router.put("/{goal_id}/guardian/config", response_model=AgentGoalGuardianConfigResponse)
def update_guardian_config(
    goal_id: int,
    body: AgentGoalGuardianConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新目标守护配置（文档 Section 13.2）"""
    goal = _get_goal_guardian_and_check(db, goal_id, current_user)

    config = agent_goal_guardian_service.ensure_config_for_goal(db, goal)

    # 只更新传入的字段
    update_data = body.model_dump(exclude_unset=True)

    # 不允许前端更新 allow_auto_replan_apply
    update_data.pop("allow_auto_replan_apply", None)

    for key, value in update_data.items():
        if value is not None:
            setattr(config, key, 1 if value is True else (0 if value is False else value))

    db.commit()
    db.refresh(config)

    logger.info("更新目标 %s 守护配置: %s", goal_id, list(update_data.keys()))

    return AgentGoalGuardianConfigResponse(
        goal_id=config.goal_id,
        enabled=bool(config.enabled),
        guard_level=config.guard_level,
        check_interval_minutes=config.check_interval_minutes,
        stale_action_hours=config.stale_action_hours,
        due_soon_days=config.due_soon_days,
        progress_lag_threshold=float(config.progress_lag_threshold),
        low_quality_threshold=float(config.low_quality_threshold),
        allow_auto_prepare=bool(config.allow_auto_prepare),
        allow_auto_remedial=bool(config.allow_auto_remedial),
        allow_auto_replan_suggestion=bool(config.allow_auto_replan_suggestion),
        last_checked_at=config.last_checked_at,
        next_check_at=config.next_check_at,
    )


# ── 13.3 手动触发守护 ──────────────────────────────────────────

@router.post("/{goal_id}/guardian/run", response_model=AgentGoalGuardianRunTriggerResponse)
def run_guardian_manually(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动触发目标守护检查（文档 Section 13.3）"""
    goal = _get_goal_guardian_and_check(db, goal_id, current_user)

    try:
        result = agent_goal_guardian_service.guard_goal(
            db=db,
            goal_id=goal_id,
            trigger_type="manual",
        )
        db.commit()
        return AgentGoalGuardianRunTriggerResponse(
            guardian_run_id=result.get("guardian_run_id", 0),
            goal_id=goal_id,
            status=result.get("status", "unknown"),
            risk_level=result.get("risk_level"),
            summary=result.get("summary"),
            events_created=result.get("events_created", 0),
            auto_prepare_triggered=result.get("auto_prepare_triggered", False),
        )
    except Exception as e:
        db.rollback()
        logger.exception("手动守护目标 %s 失败", goal_id)
        raise HTTPException(status_code=500, detail=f"守护执行失败: {str(e)}")


# ── 13.4 获取守护记录 ──────────────────────────────────────────

@router.get("/{goal_id}/guardian/runs", response_model=list[AgentGoalGuardianRunResponse])
def list_guardian_runs(
    goal_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取目标守护执行记录（文档 Section 13.4）"""
    goal = _get_goal_guardian_and_check(db, goal_id, current_user)

    runs = (
        db.query(AgentGoalGuardianRun)
        .filter(AgentGoalGuardianRun.goal_id == goal_id)
        .order_by(desc(AgentGoalGuardianRun.started_at))
        .limit(limit)
        .all()
    )

    return runs


# ── 13.5 获取守护事件 ──────────────────────────────────────────

@router.get("/{goal_id}/guardian/events", response_model=list[AgentGoalGuardianEventResponse])
def list_guardian_events(
    goal_id: int,
    status: str = Query(default=None, pattern="^(unread|read|dismissed)$"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取目标守护事件/提醒（文档 Section 13.5）"""
    goal = _get_goal_guardian_and_check(db, goal_id, current_user)

    query = db.query(AgentGoalGuardianEvent).filter(
        AgentGoalGuardianEvent.goal_id == goal_id,
    )
    if status:
        query = query.filter(AgentGoalGuardianEvent.status == status)

    events = (
        query.order_by(desc(AgentGoalGuardianEvent.created_at))
        .limit(limit)
        .all()
    )

    return [
        AgentGoalGuardianEventResponse(
            id=e.id,
            goal_id=e.goal_id,
            event_type=e.event_type,
            severity=e.severity,
            title=e.title,
            message=e.message,
            action_type=e.action_type,
            action_payload=e.action_payload_json,
            status=e.status,
            created_at=e.created_at,
        )
        for e in events
    ]


# ── 13.6 标记事件已读 ──────────────────────────────────────────

@router.post("/{goal_id}/guardian/events/{event_id}/read")
def read_guardian_event(
    goal_id: int,
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标记守护事件为已读（文档 Section 13.6）"""
    goal = _get_goal_guardian_and_check(db, goal_id, current_user)

    event = db.query(AgentGoalGuardianEvent).filter(
        AgentGoalGuardianEvent.id == event_id,
        AgentGoalGuardianEvent.goal_id == goal_id,
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")

    event.status = "read"
    event.read_at = now_shanghai()
    db.commit()

    return {"status": "ok", "event_id": event_id}


# ── 13.7 忽略事件 ──────────────────────────────────────────────

@router.post("/{goal_id}/guardian/events/{event_id}/dismiss")
def dismiss_guardian_event(
    goal_id: int,
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """忽略守护事件（文档 Section 13.7）"""
    goal = _get_goal_guardian_and_check(db, goal_id, current_user)

    event = db.query(AgentGoalGuardianEvent).filter(
        AgentGoalGuardianEvent.id == event_id,
        AgentGoalGuardianEvent.goal_id == goal_id,
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")

    event.status = "dismissed"
    event.dismissed_at = now_shanghai()
    db.commit()

    return {"status": "ok", "event_id": event_id}
