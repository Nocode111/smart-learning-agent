"""
目标Agent多轮自主推进循环 数据模型（文档 Section 13）

包含两张表：
- AgentGoalLoopRun：一次自主推进循环的整体过程
- AgentGoalLoopIteration：循环里每一轮的 Think/Act/Observe/Evaluate
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Text

from app.database import Base


class AgentGoalLoopRun(Base):
    """目标循环运行主表（文档 Section 12.2 / 13.2）"""

    __tablename__ = "agent_goal_loop_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loop_uuid = Column(String(64), nullable=False, unique=True)

    goal_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    conversation_id = Column(BigInteger)

    trigger_type = Column(String(32), nullable=False, default="user_click")
    status = Column(String(32), nullable=False, default="running")

    max_iterations = Column(Integer, nullable=False, default=3)
    completed_iterations = Column(Integer, nullable=False, default=0)
    max_seconds = Column(Integer, nullable=False, default=60)

    stop_reason = Column(String(64))
    action_required = Column(Integer, nullable=False, default=0)
    action_type = Column(String(64))
    action_payload_json = Column(JSON)

    summary = Column(Text)
    error_message = Column(Text)
    final_goal_snapshot_json = Column(JSON)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_goal_loop_goal", "goal_id"),
        Index("idx_goal_loop_student_course", "student_id", "course_id"),
        Index("idx_goal_loop_status", "status"),
        Index("idx_goal_loop_started_at", "started_at"),
    )


class AgentGoalLoopIteration(Base):
    """循环迭代明细表（文档 Section 12.3 / 13.2）"""

    __tablename__ = "agent_goal_loop_iterations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loop_run_id = Column(BigInteger, nullable=False)
    iteration_no = Column(Integer, nullable=False)

    goal_id = Column(BigInteger, nullable=False)
    advance_cycle_id = Column(BigInteger)
    step_id = Column(BigInteger)
    run_id = Column(BigInteger)
    reflection_id = Column(BigInteger)

    status = Column(String(32), nullable=False, default="running")
    decision_type = Column(String(64))
    thought_summary = Column(Text)
    action_summary = Column(Text)
    observation_json = Column(JSON)
    evaluation_json = Column(JSON)

    stop_after_iteration = Column(Integer, nullable=False, default=0)
    stop_reason = Column(String(64))
    error_message = Column(Text)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_loop_iter_loop", "loop_run_id"),
        Index("idx_loop_iter_goal", "goal_id"),
        Index("idx_loop_iter_advance", "advance_cycle_id"),
        Index("idx_loop_iter_status", "status"),
    )
