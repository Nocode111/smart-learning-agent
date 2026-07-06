"""
长期目标驱动 Agent Pydantic Schemas（文档 Section 7 + 执行闭环增强）

包含：
- 目标 CRUD 请求/响应
- 步骤、run、reflection 响应
- 重新规划、补救步骤请求
- 目标练习相关请求/响应
"""

from datetime import date, datetime
from pydantic import BaseModel, Field


# ── 创建目标 ──────────────────────────────────────────────────

class AgentGoalCreateRequest(BaseModel):
    """创建长期学习目标请求（文档 Section 8.1）"""
    course_id: int
    title: str | None = None
    goal_text: str
    target_score: float | None = 80
    target_knowledge_point_ids: list[int] = Field(default_factory=list)
    due_date: date | None = None


# ── 目标响应 ──────────────────────────────────────────────────

class AgentGoalResponse(BaseModel):
    """目标响应"""
    id: int
    course_id: int
    title: str
    goal_text: str
    target_score: float | None
    current_score: float | None
    progress_percent: float
    status: str
    planning_status: str
    due_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 步骤响应（增强版 — 文档 Section 7.1） ─────────────────────

class AgentGoalStepResponse(BaseModel):
    """步骤响应（含执行闭环增强字段）"""
    id: int
    goal_id: int
    step_order: int
    title: str
    description: str | None
    step_type: str
    tool_name: str | None
    expected_outcome: str | None
    status: str
    retry_count: int
    max_retries: int
    result_summary: str | None
    estimated_minutes: int | None
    last_error: str | None

    # 执行闭环增强字段
    output_type: str | None = None
    output_ref: dict | None = None
    needs_user_action: bool = False
    user_action_type: str | None = None
    user_action_status: str | None = None
    latest_run: dict | None = None
    latest_reflection: dict | None = None

    model_config = {"from_attributes": True}


# ── 计划响应 ──────────────────────────────────────────────────

class AgentGoalPlanResponse(BaseModel):
    """目标 + 步骤响应"""
    goal: AgentGoalResponse
    steps: list[AgentGoalStepResponse]


# ── 复盘响应 ──────────────────────────────────────────────────

class AgentGoalReflectionResponse(BaseModel):
    """复盘响应"""
    id: int
    goal_id: int
    step_id: int | None
    run_id: int | None
    reflection_type: str
    is_success: bool
    quality_score: float | None
    summary: str | None
    issues_json: list | None
    next_action: str | None
    suggested_new_steps_json: list | None
    applied_action_status: str | None = None
    applied_action_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 执行结果列表响应 ──────────────────────────────────────────

class AgentGoalRunListItem(BaseModel):
    """Run 列表项（文档 Section 8.1）"""
    id: int
    run_uuid: str
    status: str
    tool_name: str | None
    output_type: str | None = None
    output_ref: dict | None = None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


# ── Run 详情响应（文档 Section 7.2） ──────────────────────────

class AgentGoalRunDetailResponse(BaseModel):
    """Run 详情（聚合 QA、练习、文档、复盘）"""
    id: int
    run_uuid: str
    goal_id: int
    step_id: int
    status: str
    tool_name: str | None
    tool_args: dict | None
    tool_result: dict | None
    agent_steps: list[dict] = Field(default_factory=list)
    retrieved_chunks: list[dict] = Field(default_factory=list)
    output_type: str | None = None
    output_ref: dict | None = None
    qa: dict | None = None
    practice_session: dict | None = None
    generated_document: dict | None = None
    reflection: dict | None = None
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


# ── 执行结果响应（简化版，兼容旧接口） ────────────────────────

class AgentGoalRunResponse(BaseModel):
    """执行结果响应（简化版）"""
    run_id: int
    run_uuid: str
    goal_id: int
    step_id: int
    status: str
    text: str | None = None
    agent_steps: list[dict] = Field(default_factory=list)
    reflection: dict | None = None

    model_config = {"from_attributes": True}


# ── 目标详情响应（含步骤和复盘） ──────────────────────────────

class AgentGoalDetailResponse(BaseModel):
    """目标详情"""
    goal: AgentGoalResponse
    steps: list[AgentGoalStepResponse]
    latest_reflections: list[AgentGoalReflectionResponse]


# ── 手动完成步骤请求 ──────────────────────────────────────────

class AgentGoalStepCompleteRequest(BaseModel):
    """手动完成步骤请求"""
    result_summary: str


# ── 目标状态更新响应 ──────────────────────────────────────────

class AgentGoalStatusResponse(BaseModel):
    """目标状态变更响应"""
    id: int
    status: str
    message: str


# ── 生成计划响应 ──────────────────────────────────────────────

class AgentGoalPlanGenerateResponse(BaseModel):
    """生成计划响应"""
    goal_id: int
    planning_status: str
    step_count: int
    plan_summary: str | None
    message: str


# ── 重新规划请求（文档 Section 7.3） ──────────────────────────

class AgentGoalReplanRequest(BaseModel):
    """重新规划请求"""
    reason: str | None = None
    preserve_completed_steps: bool = True


# ── 刷新复盘请求（文档 Section 7.4） ──────────────────────────

class AgentGoalRefreshReflectionRequest(BaseModel):
    """刷新步骤复盘请求"""
    force_llm: bool = False


# ── 插入补救步骤请求（文档 Section 7.5） ──────────────────────

class AgentGoalInsertRemedialStepRequest(BaseModel):
    """插入补救步骤请求"""
    after_step_id: int
    title: str
    description: str | None = None
    step_type: str = "qa_explanation"
    tool_name: str = "qa_answer"
    tool_args: dict = Field(default_factory=dict)
    target_knowledge_point_ids: list[int] = Field(default_factory=list)


# ── 目标练习详情响应 ──────────────────────────────────────────

class GoalPracticeQuestionResponse(BaseModel):
    """练习题目"""
    id: int
    question_no: int
    stem: str
    options: list[str] | None = None
    status: str
    submitted_answer: str | None = None
    is_correct: bool | None = None

    model_config = {"from_attributes": True}


class GoalPracticeSessionResponse(BaseModel):
    """目标练习详情（文档 Section 8.6）"""
    session: dict
    questions: list[dict]


# ── 提交练习答案请求 ──────────────────────────────────────────

class GoalPracticeAnswerRequest(BaseModel):
    """提交练习答案请求（文档 Section 8.7）"""
    question_no: int
    submitted_answer: str


# ── 目标推进请求/响应（文档 Section 10） ──────────────────────────

class AgentGoalAdvanceRequest(BaseModel):
    """推进目标一次请求（文档 Section 10.1）"""
    client_request_id: str | None = None
    allow_generate_plan: bool = True
    allow_replan: bool = False
    allow_retry: bool = True
    force_step_id: int | None = None


class AgentGoalAdvanceResponse(BaseModel):
    """推进目标一次响应（文档 Section 10.2）"""
    cycle_id: int
    cycle_uuid: str
    goal_id: int
    status: str
    decision_type: str | None
    decision_reason: str | None

    selected_step_id: int | None = None
    selected_run_id: int | None = None

    action_required: bool = False
    action_type: str | None = None
    action_payload: dict | None = None

    result_summary: str | None = None
    user_message: str

    goal: dict | None = None
    step: dict | None = None
    run: dict | None = None
    reflection: dict | None = None


class AgentGoalAdvanceCycleResponse(BaseModel):
    """推进记录响应（文档 Section 10.3）"""
    id: int
    cycle_uuid: str
    goal_id: int
    status: str
    decision_type: str | None
    decision_reason: str | None
    selected_step_id: int | None
    selected_run_id: int | None
    action_required: bool
    action_type: str | None
    action_payload: dict | None
    result_summary: str | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


# ── 目标循环推进请求/响应（文档 Section 14） ──────────────────

class AgentGoalLoopRunRequest(BaseModel):
    """自主推进循环请求（文档 Section 14.1）"""
    max_iterations: int = Field(default=3, ge=1, le=5)
    max_seconds: int = Field(default=60, ge=10, le=180)
    allow_generate_plan: bool = True
    allow_replan: bool = False
    allow_retry: bool = True
    stop_on_user_action: bool = True
    trigger_type: str = "user_click"


class AgentGoalLoopIterationResponse(BaseModel):
    """循环迭代响应（文档 Section 14.2）"""
    id: int
    iteration_no: int
    status: str
    decision_type: str | None = None
    thought_summary: str | None = None
    action_summary: str | None = None
    observation: dict | None = None
    evaluation: dict | None = None
    stop_after_iteration: bool = False
    stop_reason: str | None = None
    advance_cycle_id: int | None = None
    step_id: int | None = None
    run_id: int | None = None
    reflection_id: int | None = None

    model_config = {"from_attributes": True}


class AgentGoalLoopRunResponse(BaseModel):
    """循环运行响应（文档 Section 14.3）"""
    id: int
    loop_uuid: str
    goal_id: int
    status: str
    completed_iterations: int
    max_iterations: int
    stop_reason: str | None = None
    action_required: bool = False
    action_type: str | None = None
    action_payload: dict | None = None
    summary: str | None = None
    error_message: str | None = None
    iterations: list[AgentGoalLoopIterationResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ── 用户动作请求/响应（文档 Section 9） ──────────────────────────

class AgentGoalUserActionStartRequest(BaseModel):
    """开始用户动作请求（文档 Section 9.1）"""
    action_type: str
    target_type: str | None = None
    target_id: int | None = None


class AgentGoalUserActionHeartbeatRequest(BaseModel):
    """阅读心跳请求（文档 Section 9.2）"""
    action_uuid: str
    visible: bool = True
    active_seconds: int = Field(default=5, ge=1, le=10)


class AgentGoalUserActionCompleteRequest(BaseModel):
    """手动完成用户动作请求（文档 Section 9.3）"""
    action_uuid: str | None = None
    action_type: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    trigger_auto_advance: bool = True


class AgentGoalUserActionResponse(BaseModel):
    """用户动作响应（文档 Section 9.4）"""
    id: int
    action_uuid: str
    goal_id: int
    step_id: int
    action_type: str
    status: str
    required_seconds: int
    accumulated_seconds: int
    completed: bool = False
    auto_advance_result: dict | None = None

    model_config = {"from_attributes": True}
