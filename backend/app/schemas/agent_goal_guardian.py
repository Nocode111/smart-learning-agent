"""
长期目标守护 Pydantic Schemas（文档 Section 14）

包含：
- 守护配置请求/响应
- 守护执行记录响应
- 守护事件响应
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ── 守护配置响应（文档 Section 14.1） ──────────────────────────

class AgentGoalGuardianConfigResponse(BaseModel):
    """守护配置响应"""
    goal_id: int
    enabled: bool
    guard_level: str
    check_interval_minutes: int
    stale_action_hours: int
    due_soon_days: int
    progress_lag_threshold: float
    low_quality_threshold: float
    allow_auto_prepare: bool
    allow_auto_remedial: bool
    allow_auto_replan_suggestion: bool
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── 守护配置更新请求（文档 Section 14.2） ──────────────────────

class AgentGoalGuardianConfigUpdateRequest(BaseModel):
    """更新守护配置请求"""
    enabled: bool | None = None
    guard_level: str | None = Field(default=None, pattern="^(light|normal|strict)$")
    check_interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    stale_action_hours: int | None = Field(default=None, ge=1, le=168)
    due_soon_days: int | None = Field(default=None, ge=1, le=30)
    progress_lag_threshold: float | None = Field(default=None, ge=0, le=100)
    low_quality_threshold: float | None = Field(default=None, ge=0, le=100)
    allow_auto_prepare: bool | None = None
    allow_auto_remedial: bool | None = None
    allow_auto_replan_suggestion: bool | None = None


# ── 守护执行记录响应（文档 Section 14.4） ──────────────────────

class AgentGoalGuardianRunResponse(BaseModel):
    """守护执行记录响应"""
    id: int
    run_uuid: str
    goal_id: int
    trigger_type: str
    status: str
    risk_level: str | None = None
    summary: str | None = None
    started_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── 守护事件响应（文档 Section 14.5） ──────────────────────────

class AgentGoalGuardianEventResponse(BaseModel):
    """守护事件响应"""
    id: int
    goal_id: int
    event_type: str
    severity: str
    title: str
    message: str | None = None
    action_type: str | None = None
    action_payload: dict | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 手动触发守护响应（文档 Section 14.3） ──────────────────────

class AgentGoalGuardianRunTriggerResponse(BaseModel):
    """手动触发守护响应"""
    guardian_run_id: int
    goal_id: int
    status: str
    risk_level: str | None = None
    summary: str | None = None
    events_created: int = 0
    auto_prepare_triggered: bool = False
