"""
目标推进记录模型（文档 Section 9）

记录每一次用户点击"推进目标"时 Agent 的判断和执行过程。
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Text

from app.database import Base


class AgentGoalAdvanceCycle(Base):
    """目标推进周期记录（文档 Section 9.1）"""

    __tablename__ = "agent_goal_advance_cycles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    goal_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    cycle_uuid = Column(String(64), nullable=False, unique=True)
    trigger_type = Column(String(32), nullable=False, default="user_click")
    status = Column(String(32), nullable=False, default="running")

    decision_type = Column(String(64))
    decision_reason = Column(Text)

    selected_step_id = Column(BigInteger)
    selected_run_id = Column(BigInteger)
    selected_reflection_id = Column(BigInteger)

    action_required = Column(Integer, nullable=False, default=0)
    action_type = Column(String(64))
    action_payload_json = Column(JSON)

    before_snapshot_json = Column(JSON)
    after_snapshot_json = Column(JSON)
    agent_trace_json = Column(JSON)

    result_summary = Column(Text)
    error_message = Column(Text)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_goal_advance_goal", "goal_id"),
        Index("idx_goal_advance_student_course", "student_id", "course_id"),
        Index("idx_goal_advance_status", "status"),
        Index("idx_goal_advance_decision", "decision_type"),
        Index("idx_goal_advance_started_at", "started_at"),
    )
