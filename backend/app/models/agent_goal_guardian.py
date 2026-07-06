"""
长期目标守护数据模型（文档 Section 8）

包含：
- AgentGoalGuardianConfig  目标守护配置
- AgentGoalGuardianRun     守护执行记录
- AgentGoalGuardianEvent   守护事件（提醒/通知）
- AgentGoalDailySnapshot   目标每日快照
"""

from sqlalchemy import BigInteger, Column, Date, DateTime, Index, Integer, JSON, Numeric, String, Text, Time

from app.database import Base
from app.utils.time_utils import now_shanghai


class AgentGoalGuardianConfig(Base):
    """目标守护配置表（文档 Section 8.1）"""

    __tablename__ = "agent_goal_guardian_configs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    goal_id = Column(BigInteger, nullable=False, unique=True)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    enabled = Column(Integer, nullable=False, default=1)
    guard_level = Column(String(32), nullable=False, default="normal")

    check_interval_minutes = Column(Integer, nullable=False, default=60)
    quiet_start_time = Column(Time, nullable=True)
    quiet_end_time = Column(Time, nullable=True)

    stale_action_hours = Column(Integer, nullable=False, default=12)
    due_soon_days = Column(Integer, nullable=False, default=3)
    progress_lag_threshold = Column(Numeric(5, 2), nullable=False, default=20)
    low_quality_threshold = Column(Numeric(5, 2), nullable=False, default=60)

    allow_auto_prepare = Column(Integer, nullable=False, default=1)
    allow_auto_remedial = Column(Integer, nullable=False, default=1)
    allow_auto_replan_suggestion = Column(Integer, nullable=False, default=1)
    allow_auto_replan_apply = Column(Integer, nullable=False, default=0)

    last_checked_at = Column(DateTime, nullable=True)
    next_check_at = Column(DateTime, nullable=True)
    last_guardian_run_id = Column(BigInteger, nullable=True)

    metadata_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=now_shanghai)
    updated_at = Column(DateTime, nullable=False, default=now_shanghai, onupdate=now_shanghai)

    __table_args__ = (
        Index("idx_guardian_config_student_course", "student_id", "course_id"),
        Index("idx_guardian_config_enabled_next", "enabled", "next_check_at"),
        Index("idx_guardian_config_goal", "goal_id"),
    )


class AgentGoalGuardianRun(Base):
    """目标守护执行记录表（文档 Section 8.2）"""

    __tablename__ = "agent_goal_guardian_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_uuid = Column(String(64), nullable=False, unique=True)

    goal_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    trigger_type = Column(String(64), nullable=False, default="scheduler")
    status = Column(String(32), nullable=False, default="running")

    snapshot_json = Column(JSON)
    decisions_json = Column(JSON)
    actions_json = Column(JSON)

    risk_level = Column(String(32))
    summary = Column(Text)
    error_message = Column(Text)

    started_at = Column(DateTime, nullable=False, default=now_shanghai)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=now_shanghai)

    __table_args__ = (
        Index("idx_guardian_run_goal", "goal_id"),
        Index("idx_guardian_run_student_course", "student_id", "course_id"),
        Index("idx_guardian_run_status", "status"),
        Index("idx_guardian_run_started", "started_at"),
    )


class AgentGoalGuardianEvent(Base):
    """目标守护事件表（文档 Section 8.3）"""

    __tablename__ = "agent_goal_guardian_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    goal_id = Column(BigInteger, nullable=False)
    guardian_run_id = Column(BigInteger, nullable=True)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    event_type = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False, default="info")
    title = Column(String(255), nullable=False)
    message = Column(Text)

    action_type = Column(String(64))
    action_payload_json = Column(JSON)

    status = Column(String(32), nullable=False, default="unread")
    read_at = Column(DateTime)
    dismissed_at = Column(DateTime)

    dedupe_key = Column(String(128))
    metadata_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=now_shanghai)

    __table_args__ = (
        Index("idx_guardian_event_goal", "goal_id"),
        Index("idx_guardian_event_student_status", "student_id", "status"),
        Index("idx_guardian_event_type", "event_type"),
        Index("idx_guardian_event_dedupe", "dedupe_key"),
    )


class AgentGoalDailySnapshot(Base):
    """目标每日快照表（文档 Section 8.4）"""

    __tablename__ = "agent_goal_daily_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    goal_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    snapshot_date = Column(Date, nullable=False)

    goal_status = Column(String(32), nullable=False)
    progress_percent = Column(Numeric(5, 2), nullable=False, default=0)
    completed_steps = Column(Integer, nullable=False, default=0)
    total_steps = Column(Integer, nullable=False, default=0)
    waiting_steps = Column(Integer, nullable=False, default=0)
    failed_steps = Column(Integer, nullable=False, default=0)

    latest_activity_at = Column(DateTime)
    expected_progress = Column(Numeric(5, 2))
    progress_lag = Column(Numeric(5, 2))

    practice_count = Column(Integer, nullable=False, default=0)
    avg_practice_accuracy = Column(Numeric(5, 2))

    snapshot_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=now_shanghai)

    __table_args__ = (
        Index("idx_daily_snapshot_student_course", "student_id", "course_id"),
        Index("idx_daily_snapshot_date", "snapshot_date"),
    )
