"""
长期目标驱动 Agent 数据模型（文档 Section 6）

包含四张表：
- AgentLearningGoal：长期学习目标主表
- AgentGoalStep：目标计划步骤
- AgentGoalRun：每次步骤执行记录
- AgentGoalReflection：执行后复盘
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class AgentLearningGoal(Base):
    """长期学习目标主表（文档 Section 6.1）"""

    __tablename__ = "agent_learning_goals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    conversation_id = Column(BigInteger, nullable=True)

    title = Column(String(255), nullable=False)
    goal_text = Column(Text, nullable=False)
    target_score = Column(Numeric(5, 2), nullable=True)
    current_score = Column(Numeric(5, 2), nullable=True)
    progress_percent = Column(Numeric(5, 2), nullable=False, default=0)

    target_knowledge_point_ids = Column(JSON)
    weak_knowledge_point_ids = Column(JSON)

    start_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)

    status = Column(String(32), nullable=False, default="draft")
    planning_status = Column(String(32), nullable=False, default="none")

    plan_summary = Column(Text)
    plan_json = Column(JSON)
    metadata_json = Column(JSON)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    activated_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)

    # 关联步骤
    steps = relationship("AgentGoalStep", back_populates="goal", order_by="AgentGoalStep.step_order")

    __table_args__ = (
        Index("idx_agent_goal_student_course", "student_id", "course_id"),
        Index("idx_agent_goal_status", "status"),
        Index("idx_agent_goal_due_date", "due_date"),
        Index("idx_agent_goal_updated_at", "updated_at"),
    )


class AgentGoalStep(Base):
    """目标计划步骤表（文档 Section 6.2）"""

    __tablename__ = "agent_goal_steps"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    goal_id = Column(BigInteger, ForeignKey("agent_learning_goals.id"), nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    step_order = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)

    step_type = Column(String(64), nullable=False)
    tool_name = Column(String(64), nullable=True)
    tool_args_json = Column(JSON)

    expected_outcome = Column(Text)
    success_criteria_json = Column(JSON)

    target_knowledge_point_ids = Column(JSON)
    estimated_minutes = Column(Integer, nullable=True)

    # 执行闭环增强字段（文档 Section 6.1）
    depends_on_step_ids = Column(JSON)
    execution_mode = Column(String(32), nullable=False, default="manual_trigger")
    output_type = Column(String(64))
    output_ref_json = Column(JSON)
    quality_gate_json = Column(JSON)
    needs_user_action = Column(Integer, nullable=False, default=0)
    user_action_type = Column(String(64))
    user_action_status = Column(String(32))

    status = Column(String(32), nullable=False, default="pending")
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=1)

    last_run_id = Column(BigInteger, nullable=True)
    last_error = Column(Text)
    result_summary = Column(Text)
    reflection_json = Column(JSON)
    metadata_json = Column(JSON)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 关联
    goal = relationship("AgentLearningGoal", back_populates="steps")

    __table_args__ = (
        Index("idx_agent_goal_step_goal", "goal_id"),
        Index("idx_agent_goal_step_student_course", "student_id", "course_id"),
        Index("idx_agent_goal_step_status", "status"),
        Index("idx_agent_goal_step_type", "step_type"),
    )


class AgentGoalRun(Base):
    """每次步骤执行记录（文档 Section 6.3）"""

    __tablename__ = "agent_goal_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    goal_id = Column(BigInteger, nullable=False)
    step_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    conversation_id = Column(BigInteger, nullable=True)

    run_uuid = Column(String(64), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="running")

    tool_name = Column(String(64), nullable=True)
    tool_args_json = Column(JSON)
    tool_result_json = Column(JSON)

    agent_steps_json = Column(JSON)
    retrieved_chunks_json = Column(JSON)

    output_message_id = Column(BigInteger, nullable=True)
    qa_id = Column(BigInteger, nullable=True)
    practice_session_id = Column(BigInteger, nullable=True)
    generated_document_id = Column(BigInteger, nullable=True)

    # 执行闭环增强字段（文档 Section 6.2）
    output_type = Column(String(64))
    output_ref_json = Column(JSON)
    quality_gate_result_json = Column(JSON)
    user_action_required = Column(Integer, nullable=False, default=0)
    user_action_status = Column(String(32))

    error_message = Column(Text)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_goal_run_goal", "goal_id"),
        Index("idx_agent_goal_run_step", "step_id"),
        Index("idx_agent_goal_run_status", "status"),
        Index("idx_agent_goal_run_student_course", "student_id", "course_id"),
    )


class AgentGoalReflection(Base):
    """执行后复盘表（文档 Section 6.4）"""

    __tablename__ = "agent_goal_reflections"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    goal_id = Column(BigInteger, nullable=False)
    step_id = Column(BigInteger, nullable=True)
    run_id = Column(BigInteger, nullable=True)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)

    reflection_type = Column(String(64), nullable=False, default="step_after_run")
    is_success = Column(Integer, nullable=False, default=0)
    quality_score = Column(Numeric(5, 2), nullable=True)

    summary = Column(Text)
    issues_json = Column(JSON)
    next_action = Column(String(64))
    suggested_step_patch_json = Column(JSON)
    suggested_new_steps_json = Column(JSON)

    # 执行闭环增强字段（文档 Section 6.4）
    applied_action_status = Column(String(32))
    applied_action_message = Column(Text)

    raw_llm_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_goal_reflection_goal", "goal_id"),
        Index("idx_agent_goal_reflection_step", "step_id"),
        Index("idx_agent_goal_reflection_run", "run_id"),
        Index("idx_agent_goal_reflection_type", "reflection_type"),
    )
