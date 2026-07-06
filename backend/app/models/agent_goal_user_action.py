"""
学习步骤用户动作数据模型（文档 Section 8）

agent_goal_user_actions — 记录用户对目标步骤的真实学习动作
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String

from app.database import Base


class AgentGoalUserAction(Base):
    """用户学习动作记录表（文档 Section 8.2）"""

    __tablename__ = "agent_goal_user_actions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    action_uuid = Column(String(64), nullable=False, unique=True)

    goal_id = Column(BigInteger, nullable=False)
    step_id = Column(BigInteger, nullable=False)
    run_id = Column(BigInteger)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    action_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="started")

    target_type = Column(String(64))
    target_id = Column(BigInteger)

    required_seconds = Column(Integer, nullable=False, default=30)
    accumulated_seconds = Column(Integer, nullable=False, default=0)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_heartbeat_at = Column(DateTime)
    completed_at = Column(DateTime)

    metadata_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_goal_user_action_goal", "goal_id"),
        Index("idx_goal_user_action_step", "step_id"),
        Index("idx_goal_user_action_student_course", "student_id", "course_id"),
        Index("idx_goal_user_action_status", "status"),
        Index("idx_goal_user_action_type", "action_type"),
    )
